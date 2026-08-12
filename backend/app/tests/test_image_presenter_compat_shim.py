"""app/services/image_presenter.py::resolve_item_images -- the compat shim that lets
generic_flow_engine.py's one read site (_image_for_step) work unchanged whether or not a
catalog item has been migrated onto the Universal Image Processing Pipeline yet.

The "falls back to the legacy JSON list when no Image rows exist" half of this is already
exercised indirectly by every existing niche test (test_niche_restaurant.py etc. all pass
today using nothing but CatalogItem.images placeholder URLs -- if the fallback were
broken, those would already be failing). This file covers the other half: once ready
Image rows exist, they take priority over the legacy list, and a replaced/superseded
Image row is correctly excluded.
"""

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.image import Image
from app.models.restaurant import Restaurant
from app.services.image_presenter import resolve_item_images


async def _make_item(db_session) -> tuple[Restaurant, CatalogItem]:
    restaurant = Restaurant(
        name="Compat Shim Test Biz",
        slug="compat-shim-test-biz",
        whatsapp_phone_number_id="COMPATSHIM_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    category = CatalogCategory(restaurant_id=restaurant.id, name="Category")
    db_session.add(category)
    await db_session.flush()
    item = CatalogItem(
        restaurant_id=restaurant.id, category_id=category.id, name="Item",
        images=["https://placehold.co/600x400?text=Legacy"],
    )
    db_session.add(item)
    await db_session.commit()
    return restaurant, item


async def test_falls_back_to_legacy_json_list_when_no_image_rows_exist(db_session):
    restaurant, item = await _make_item(db_session)
    urls = await resolve_item_images(db_session, item, restaurant.id)
    assert urls == ["https://placehold.co/600x400?text=Legacy"]


async def test_prefers_ready_image_table_row_over_legacy_list(db_session):
    restaurant, item = await _make_item(db_session)
    db_session.add(Image(
        restaurant_id=restaurant.id,
        image_type="product",
        catalog_item_id=item.id,
        original_key="images/x/original.jpg",
        original_format="jpg",
        original_width=800,
        original_height=800,
        original_size_bytes=1000,
        status="ready",
        variants={"website": {"key": "images/x/derived/website.webp", "format": "webp", "width": 800, "height": 800, "size_bytes": 500}},
    ))
    await db_session.commit()

    urls = await resolve_item_images(db_session, item, restaurant.id)
    assert urls == ["https://fake-image-storage.test/images/x/derived/website.webp"]


async def test_ignores_still_processing_and_superseded_image_rows(db_session):
    restaurant, item = await _make_item(db_session)
    # Still processing -- not "current" yet.
    db_session.add(Image(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key="images/proc/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="processing",
    ))
    # Ready, but superseded by a later replace() -- must not resurface.
    superseded_id_holder = Image(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key="images/old/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="ready",
        variants={"website": {"key": "images/old/derived/website.webp", "format": "webp", "width": 800, "height": 800, "size_bytes": 500}},
    )
    db_session.add(superseded_id_holder)
    await db_session.flush()
    superseded_id_holder.replaced_by_image_id = superseded_id_holder.id  # stand-in "was replaced" marker
    await db_session.commit()

    urls = await resolve_item_images(db_session, item, restaurant.id)
    # Neither the processing row nor the superseded row counts as "current" -- falls back.
    assert urls == ["https://placehold.co/600x400?text=Legacy"]
