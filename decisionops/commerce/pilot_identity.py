"""Pilot member authentication. Demo accounts have no pilot memberships."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from getpass import getpass
from hashlib import sha256
import re
from secrets import token_urlsafe
from threading import BoundedSemaphore
from urllib.parse import urlsplit
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock

SESSION_TTL = timedelta(hours=8)
INVITE_TTL = timedelta(hours=24)
RATE_WINDOW = 900
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
STORE_ID = re.compile(r'[a-z][a-z0-9-]{0,62}')
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
HASHER = PasswordHasher()
HASH_SLOTS = BoundedSemaphore(4)


def digest(value):
    return sha256(value.encode()).hexdigest()


def normalize_email(value):
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL.fullmatch(email) or not email.isascii():
        raise ValueError('Use a valid email address')
    return email


def hash_password(password):
    if not 14 <= len(password) <= 256:
        raise ValueError('Use a password of 14 to 256 characters')
    return HASHER.hash(password)


def bootstrap(engine, store_id, store_name, email, password):
    """Enroll the first approver for a new pilot store from a trusted shell."""
    if not STORE_ID.fullmatch(store_id) or not 1 <= len(store_name.strip()) <= 120:
        raise ValueError('Use a store slug and a name of 1 to 120 characters')
    email = normalize_email(email)
    password_hash = hash_password(password)
    user_id = uuid4().hex
    with engine.begin() as connection:
        connection.execute(db.pilot_stores.insert().values(id=store_id, name=store_name.strip()))
        connection.execute(db.pilot_users.insert().values(id=user_id, email=email, password_hash=password_hash))
        connection.execute(db.pilot_memberships.insert().values(store_id=store_id, user_id=user_id, role='approver'))


@dataclass(frozen=True)
class Principal:
    store_id: str
    user_id: str
    role: str
    email: str


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Credentials(EmptyBody):
    email: str
    password: SecretStr


class Invitation(EmptyBody):
    email: str
    role: str = 'staff'


class InvitationAcceptance(EmptyBody):
    token: SecretStr
    password: SecretStr


class Identity:
    def __init__(self, engine, origin):
        url = urlsplit(origin)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.path or url.query or url.fragment):
            raise ValueError('Set COMMERCE_PILOT_ORIGIN to an exact public origin')
        self.secure = url.scheme == 'https'
        if not self.secure and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('The hosted pilot requires HTTPS')
        self.engine = engine
        self.origin = origin
        self.cookie = '__Host-decisionops-pilot' if self.secure else 'decisionops-pilot-local'
        self.dummy_hash = HASHER.hash(token_urlsafe(32))

    @contextmanager
    def _write(self):
        # A waiter must re-evaluate an invitation after its concurrent consumer
        # commits. Read committed also lets counter upserts use the newest value.
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection:
            with connection.begin():
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                yield connection

    def mutation(self, request: Request):
        if request.headers.get('origin') != self.origin:
            raise HTTPException(403, 'Origin is not permitted')
        if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Use application/json')

    def _token_hash(self, request):
        token = request.cookies.get(self.cookie, '')
        return digest(token) if TOKEN.fullmatch(token) else None

    def _user(self, connection, request):
        token_hash = self._token_hash(request)
        if token_hash is None:
            return None
        return connection.execute(sa.select(db.pilot_users).join(db.pilot_sessions).where(
            db.pilot_sessions.c.token_hash == token_hash,
            db.pilot_sessions.c.expires_at > sa.func.clock_timestamp(),
        )).mappings().one_or_none()

    def staff(self, request: Request, store_id: str) -> Principal:
        if request.method not in ('GET', 'HEAD'):
            self.mutation(request)
        with self.engine.connect() as connection:
            user = self._user(connection, request)
            if user is None:
                raise HTTPException(401, 'Merchant sign-in required')
            role = connection.execute(sa.select(db.pilot_memberships.c.role).where(
                db.pilot_memberships.c.user_id == user['id'], db.pilot_memberships.c.store_id == store_id,
            )).scalar_one_or_none()
        if role is None:
            raise HTTPException(404, 'Store not found')
        return Principal(store_id, user['id'], role, user['email'])

    def approver(self, request: Request, store_id: str) -> Principal:
        principal = self.staff(request, store_id)
        if principal.role != 'approver':
            raise HTTPException(403, 'Approver permission required')
        return principal

    def _profile(self, connection, user):
        members = db.pilot_memberships
        stores = db.pilot_stores
        rows = connection.execute(sa.select(stores.c.id, stores.c.name, members.c.role)
            .select_from(stores.join(members)).where(members.c.user_id == user['id'])
            .order_by(stores.c.id)).mappings()
        return {'email': user['email'], 'stores': [dict(row) for row in rows]}

    def _new_session(self, connection, request, response, user):
        sessions = db.pilot_sessions
        now = clock(connection)
        old = self._token_hash(request)
        if old:
            connection.execute(sessions.delete().where(sessions.c.token_hash == old))
        connection.execute(sessions.delete().where(sessions.c.user_id == user['id'], sessions.c.expires_at <= now))
        token = token_urlsafe(32)
        connection.execute(sessions.insert().values(
            token_hash=digest(token), user_id=user['id'], expires_at=now + SESSION_TTL,
        ))
        response.set_cookie(self.cookie, token, max_age=int(SESSION_TTL.total_seconds()),
                            path='/', secure=self.secure, httponly=True, samesite='lax')
        return self._profile(connection, user)

    def _allow(self, request, kind, subject):
        # The HTTPS ingress owns the network budget. The app owns the identity budget.
        limits = db.pilot_login_limits
        with self._write() as connection:
            window = int(clock(connection).timestamp()) // RATE_WINDOW
            connection.execute(limits.delete().where(limits.c.window_id < window - 1))
            cap = 10
            operation = insert(limits).values(
                kind=f'{kind}-subject', subject_hash=digest(subject), window_id=window, attempts=1,
            )
            hits = connection.execute(operation.on_conflict_do_update(
                index_elements=list(limits.primary_key.columns),
                set_={'attempts': sa.func.least(limits.c.attempts + 1, cap + 1)},
            ).returning(limits.c.attempts)).scalar_one()
        if hits > cap:
            raise HTTPException(429, 'Too many attempts. Try again later.',
                                headers={'Retry-After': str(RATE_WINDOW)})

    def login(self, request: Request, response: Response, body: Credentials):
        try:
            email = normalize_email(body.email)
        except ValueError:
            email = ''
        self._allow(request, 'login', email)
        password = body.password.get_secret_value()
        if not 14 <= len(password) <= 256:
            raise HTTPException(401, 'Invalid sign-in credentials')
        with self.engine.connect() as connection:
            user = connection.execute(sa.select(db.pilot_users).where(db.pilot_users.c.email == email)).mappings().one_or_none()
        if not HASH_SLOTS.acquire(blocking=False):
            raise HTTPException(503, 'Sign-in is busy. Try again shortly.')
        try:
            authenticated = HASHER.verify(user['password_hash'] if user else self.dummy_hash, password)
        except Argon2Error:
            authenticated = False
        finally:
            HASH_SLOTS.release()
        if not (user and authenticated):
            raise HTTPException(401, 'Invalid sign-in credentials')
        with self._write() as connection:
            return self._new_session(connection, request, response, user)

    def session(self, request: Request):
        with self.engine.connect() as connection:
            user = self._user(connection, request)
            if user is None:
                raise HTTPException(401, 'Merchant sign-in required')
            return self._profile(connection, user)

    def logout(self, request: Request, response: Response, body: EmptyBody):
        token = self._token_hash(request)
        if token is not None:
            with self._write() as connection:
                connection.execute(db.pilot_sessions.delete().where(db.pilot_sessions.c.token_hash == token))
        response.delete_cookie(self.cookie, path='/', secure=self.secure, httponly=True, samesite='lax')
        return {'signed_out': True}

    def invite(self, body: Invitation, principal: Principal):
        try:
            email = normalize_email(body.email)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if body.role not in ('staff', 'approver'):
            raise HTTPException(422, 'Choose staff or approver')
        token = token_urlsafe(32)
        members = db.pilot_memberships
        invites = db.pilot_invites
        with self._write() as connection:
            member = connection.execute(sa.select(members.c.user_id)
                .join(db.pilot_users).where(members.c.store_id == principal.store_id,
                                           db.pilot_users.c.email == email)).first()
            if member:
                raise HTTPException(409, 'An account with that email already belongs to this store')
            now = clock(connection)
            expires = now + INVITE_TTL
            connection.execute(invites.insert().values(
                token_hash=digest(token), store_id=principal.store_id, email=email, role=body.role, expires_at=expires,
            ))
        return {'token': token, 'expires_at': expires}

    def accept(self, request: Request, response: Response, body: InvitationAcceptance):
        token = body.token.get_secret_value()
        token_hash = digest(token) if TOKEN.fullmatch(token) else None
        self._allow(request, 'accept', token_hash or '')
        invites, users = db.pilot_invites, db.pilot_users
        with self._write() as connection:
            invite = connection.execute(sa.select(invites).where(
                invites.c.token_hash == token_hash, invites.c.used_at.is_(None),
                invites.c.expires_at > sa.func.clock_timestamp(),
            ).with_for_update()).mappings().one_or_none()
            if not invite:
                raise HTTPException(404, 'Invitation is invalid or expired')
            user = connection.execute(sa.select(users).where(users.c.email == invite['email'])).mappings().one_or_none()
            current = self._user(connection, request)
            if user:
                if not current or current['id'] != user['id']:
                    raise HTTPException(409, 'Sign in with the invited email before accepting')
            else:
                if current:
                    raise HTTPException(409, 'Sign out before registering the invited email')
                if not HASH_SLOTS.acquire(blocking=False):
                    raise HTTPException(503, 'Sign-in is busy. Try again shortly.')
                try:
                    password_hash = hash_password(body.password.get_secret_value())
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
                finally:
                    HASH_SLOTS.release()
                user = connection.execute(insert(users).values(
                    id=uuid4().hex, email=invite['email'], password_hash=password_hash,
                ).on_conflict_do_nothing(index_elements=[users.c.email]).returning(users)).mappings().one_or_none()
                if user is None:
                    raise HTTPException(409, 'Sign in with the invited email before accepting')
            # A second invite cannot replace an existing role.
            connection.execute(insert(db.pilot_memberships).values(
                store_id=invite['store_id'], user_id=user['id'], role=invite['role'],
            ).on_conflict_do_nothing())
            connection.execute(invites.update().where(invites.c.token_hash == token_hash)
                               .values(used_at=clock(connection)))
            return self._new_session(connection, request, response, user)


def install_identity(app: FastAPI, engine, *, origin: str) -> Identity:
    identity = Identity(engine, origin)
    router = APIRouter(prefix='/pilot-api')
    strict = [Depends(identity.mutation)]
    router.add_api_route('/login', identity.login, methods=['POST'], dependencies=strict)
    router.add_api_route('/logout', identity.logout, methods=['POST'], dependencies=strict)
    router.add_api_route('/session', identity.session, methods=['GET'])
    router.add_api_route('/invites/accept', identity.accept, methods=['POST'], dependencies=strict)

    @router.post('/stores/{store_id}/invites', status_code=201)
    def invite(body: Invitation, principal: Principal = Depends(identity.approver)):
        return identity.invite(body, principal)

    app.include_router(router)
    return identity


def main():
    from .database import database_engine

    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest='command', required=True).add_parser('bootstrap')
    command.add_argument('--store-id', required=True)
    command.add_argument('--store-name', required=True)
    command.add_argument('--email', required=True)
    args = parser.parse_args()
    password = getpass('New merchant password: ')
    if getpass('Confirm merchant password: ') != password:
        parser.error('Passwords must match')
    engine = database_engine()
    try:
        bootstrap(engine, args.store_id, args.store_name, args.email, password)
    except (ValueError, sa.exc.IntegrityError):
        parser.error('Use a new store slug, a new email address, and a password of 14 to 256 characters')
    finally:
        engine.dispose()
    print('Pilot merchant enrolled')


if __name__ == '__main__':
    main()
