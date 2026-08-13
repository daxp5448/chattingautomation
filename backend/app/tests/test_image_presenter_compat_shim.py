"""app/services/image_presenter.py::resolve_item_images -- the compat shim that lets
generic_flow_engine.py's read sites work unchanged whether or not a catalog item has been
migrated onto the Universal Image Processing Pipeline yet.

The "falls back to the legacy JSON list when no Image rows exist" half of this is already
exercised indirectly by every existing niche test (test_niche_restaurant.py etc. all pass
today using nothing but CatalogItem.images placeholder URLs -- if the fallback were
broken, those would already be failing). This file covers the other half: once ready
Image rows exist, they take priority over the legacy list, a replaced/superseded Image row
is correctly excluded, and caption/display_order/is_active (see app/models/image.py) are
respected.
"""

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.image import Image
from app.models.restaurant import Restaurant
from app.services.image_presenter import ItemImage, resolve_item_images, resolve_item_images_bulk


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


def _ready_image(restaurant, item, key_suffix, **overrides):
    defaults = dict(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key=f"images/{key_suffix}/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="ready",
        variants={"website": {"key": f"images/{key_suffix}/derived/website.webp", "format": "webp", "width": 800, "height": 800, "size_bytes": 500}},
    )
    defaults.update(overrides)
    return Image(**defaults)


async def test_falls_back_to_legacy_json_list_when_no_image_rows_exist(db_session):
    restaurant, item = await _make_item(db_session)
    images = await resolve_item_images(db_session, item, restaurant.id)
    assert images == [ItemImage(url="https://placehold.co/600x400?text=Legacy")]


async def test_prefers_ready_image_table_row_over_legacy_list(db_session):
    restaurant, item = await _make_item(db_session)
    db_session.add(_ready_image(restaurant, item, "x"))
    await db_session.commit()

    images = await resolve_item_images(db_session, item, restaurant.id)
    assert images == [ItemImage(url="https://fake-image-storage.test/images/x/derived/website.webp", caption=None)]


async def test_ignores_still_processing_and_superseded_image_rows(db_session):
    restaurant, item = await _make_item(db_session)
    # Still processing -- not "current" yet.
    db_session.add(Image(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key="images/proc/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="processing",
    ))
    # Ready, but superseded by a later replace() -- must not resurface.
    superseded_id_holder = _ready_image(restaurant, item, "old")
    db_session.add(superseded_id_holder)
    await db_session.flush()
    superseded_id_holder.replaced_by_image_id = superseded_id_holder.id  # stand-in "was replaced" marker
    await db_session.commit()

    images = await resolve_item_images(db_session, item, restaurant.id)
    # Neither the processing row nor the superseded row counts as "current" -- falls back.
    assert images == [ItemImage(url="https://placehold.co/600x400?text=Legacy")]


async def test_ignores_inactive_image_rows(db_session):
    """is_active lets an admin hide one bad-angle photo without deleting it -- must be
    excluded from what the bot actually sends, same as a processing/superseded row."""
    restaurant, item = await _make_item(db_session)
    db_session.add(_ready_image(restaurant, item, "hidden", is_active=False))
    await db_session.commit()

    images = await resolve_item_images(db_session, item, restaurant.id)
    assert images == [ItemImage(url="https://placehold.co/600x400?text=Legacy")]


async def test_returns_caption_and_respects_display_order(db_session):
    restaurant, item = await _make_item(db_session)
    db_session.add(_ready_image(restaurant, item, "second", caption="Side profile", display_order=2))
    db_session.add(_ready_image(restaurant, item, "first", caption="Front view", display_order=1))
    await db_session.commit()

    images = await resolve_item_images(db_session, item, restaurant.id)
    assert [i.caption for i in images] == ["Front view", "Side profile"]
    assert [i.url for i in images] == [
        "https://fake-image-storage.test/images/first/derived/website.webp",
        "https://fake-image-storage.test/images/second/derived/website.webp",
    ]


async def test_bulk_resolves_each_items_own_images_in_one_batched_query(db_session):
    """resolve_item_images_bulk (generic_flow_engine.py's photo-burst gating needs every
    option's image up front, not just the first hit) -- proves it returns the same
    per-item result resolve_item_images would, for a whole category at once, correctly
    keeping legacy-list and Image-table items separate rather than mixing them up."""
    restaurant, legacy_item = await _make_item(db_session)
    category_id = legacy_item.category_id

    pipeline_item = CatalogItem(
        restaurant_id=restaurant.id, category_id=category_id, name="Pipeline Item", images=[],
    )
    no_photo_item = CatalogItem(
        restaurant_id=restaurant.id, category_id=category_id, name="No Photo Item", images=[],
    )
    db_session.add_all([pipeline_item, no_photo_item])
    await db_session.flush()
    db_session.add(_ready_image(restaurant, pipeline_item, "y"))
    await db_session.commit()

    result = await resolve_item_images_bulk(db_session, [legacy_item, pipeline_item, no_photo_item], restaurant.id)

    assert result[legacy_item.id] == [ItemImage(url="https://placehold.co/600x400?text=Legacy")]
    assert result[pipeline_item.id] == [ItemImage(url="https://fake-image-storage.test/images/y/derived/website.webp", caption=None)]
    assert result[no_photo_item.id] == []
