"""Unit tests for template_purpose_mapping.py -- no DB, plain in-memory
WhatsAppTemplate instances (never persisted). All 12 niches, plus the never-invents-a-
match / never-recommends-a-non-approved-template safety guarantees.
"""

import uuid

import pytest

from app.models.enums import TemplateCategory, TemplatePurpose, TemplateStatus
from app.models.whatsapp_template import WhatsAppTemplate
from app.services.template_purpose_mapping import NICHE_RECOMMENDED_PURPOSES, recommend_templates

_NICHE_CODES = sorted(NICHE_RECOMMENDED_PURPOSES.keys())


def _template(purpose: TemplatePurpose, status: TemplateStatus = TemplateStatus.APPROVED, name: str | None = None) -> WhatsAppTemplate:
    return WhatsAppTemplate(
        id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        name=name or f"tpl_{purpose.value}_{uuid.uuid4().hex[:6]}",
        category=TemplateCategory.UTILITY,
        purpose=purpose,
        language="en",
        body_text="Hello {{1}}",
        status=status,
    )


def test_all_12_niches_are_mapped():
    assert len(_NICHE_CODES) == 12, f"expected exactly 12 niches mapped, got {len(_NICHE_CODES)}: {_NICHE_CODES}"


@pytest.mark.parametrize("niche_code", _NICHE_CODES)
def test_each_niche_recommends_its_own_approved_template_per_purpose(niche_code):
    purposes = NICHE_RECOMMENDED_PURPOSES[niche_code]
    templates = [_template(p) for p in purposes]
    recommended = recommend_templates(templates, niche_code)

    for purpose, template in zip(purposes, templates):
        assert recommended[purpose] is template, f"{niche_code}/{purpose}: expected the matching approved template"


@pytest.mark.parametrize("niche_code", _NICHE_CODES)
def test_missing_purpose_recommends_none_not_a_wrong_guess(niche_code):
    """A niche whose tenant has zero templates at all -- every purpose maps to None,
    never a fabricated/wrong-purpose substitute."""
    recommended = recommend_templates([], niche_code)
    assert all(v is None for v in recommended.values())
    assert set(recommended.keys()) == set(NICHE_RECOMMENDED_PURPOSES[niche_code])


def test_non_approved_template_is_never_recommended():
    draft = _template(TemplatePurpose.OFFER, status=TemplateStatus.DRAFT)
    pending = _template(TemplatePurpose.OFFER, status=TemplateStatus.PENDING)
    rejected = _template(TemplatePurpose.OFFER, status=TemplateStatus.REJECTED)
    recommended = recommend_templates([draft, pending, rejected], "restaurant")
    assert recommended[TemplatePurpose.OFFER] is None


def test_approved_template_wins_over_non_approved_same_purpose():
    rejected = _template(TemplatePurpose.OFFER, status=TemplateStatus.REJECTED, name="tpl_a")
    approved = _template(TemplatePurpose.OFFER, status=TemplateStatus.APPROVED, name="tpl_b")
    recommended = recommend_templates([rejected, approved], "restaurant")
    assert recommended[TemplatePurpose.OFFER] is approved


def test_unknown_niche_code_falls_back_to_every_purpose():
    template = _template(TemplatePurpose.GENERAL)
    recommended = recommend_templates([template], "some_future_niche_not_yet_mapped")
    assert set(recommended.keys()) == set(TemplatePurpose)
    assert recommended[TemplatePurpose.GENERAL] is template


def test_none_niche_code_falls_back_to_every_purpose():
    """A Custom/Legacy-engine business with no niche_type at all."""
    recommended = recommend_templates([], None)
    assert set(recommended.keys()) == set(TemplatePurpose)


def test_a_tenants_own_templates_never_leak_into_a_different_tenants_recommendation():
    """Not a DB-level isolation test (that's test_template_recommendations.py's job) --
    proves the pure function itself only ever considers the exact list handed to it,
    never reaches for global/other-tenant state."""
    tenant_a_templates = [_template(TemplatePurpose.OFFER, name="tenant_a_offer")]
    tenant_b_templates = [_template(TemplatePurpose.OFFER, name="tenant_b_offer")]

    rec_a = recommend_templates(tenant_a_templates, "restaurant")
    rec_b = recommend_templates(tenant_b_templates, "restaurant")

    assert rec_a[TemplatePurpose.OFFER] is tenant_a_templates[0]
    assert rec_b[TemplatePurpose.OFFER] is tenant_b_templates[0]
    assert rec_a[TemplatePurpose.OFFER] is not rec_b[TemplatePurpose.OFFER]
