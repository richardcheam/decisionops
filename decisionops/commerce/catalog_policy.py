"""Read-only image-ID and SKU checks shared by catalog cases and evaluation."""


def assess(case):
    """Return (action, proposed image ID, reason) for scoped catalog records."""
    sku = case['sku']
    current = case['current_image_id']
    images = case['images']
    image_ids = [row['id'] for row in images]
    if len(image_ids) != len(set(image_ids)):
        return 'review', None, 'Resolve conflicting image mappings before changing the listing.'
    mapped = {row['id']: row for row in images if row['verified'] is True}
    supplier = case['supplier']
    if not isinstance(supplier, dict) or supplier.get('verified') is not True or supplier.get('sku') != sku:
        return 'review', None, 'Verify the supplier record for this SKU.'
    supplied = supplier.get('image_id')
    if supplied not in mapped or mapped[supplied]['sku'] != sku:
        return 'review', None, 'Resolve the disagreement between the supplier image and the verified SKU mapping.'
    if current not in mapped:
        return 'review', None, 'Verify the mapping for the current image before changing the listing.'
    if mapped[current]['sku'] == sku:
        return 'keep', None, 'The current image is verified for this SKU. No change is needed.'
    return 'relink', supplied, 'The current image is verified for another SKU. The supplier and mapping agree on the proposed image.'
