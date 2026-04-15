"""Unit tests for claim text normalizer."""

from __future__ import annotations

import pytest

from swarm_reasoning.pipeline.nodes.intake_normalizer import (
    MAX_NORMALIZED_LENGTH,
    NormalizeResult,
    normalize_claim_text,
)


class TestLowercaseConversion:
    def test_basic_uppercase(self):
        result = normalize_claim_text("BIDEN SIGNED THE ORDER")
        assert result.normalized == "biden signed the order"

    def test_mixed_case(self):
        result = normalize_claim_text("Biden Said that HE Issued a Federal Vaccine Mandate")
        assert result.normalized == "biden said that he issued a federal vaccine mandate"

    def test_unicode_casefold(self):
        result = normalize_claim_text("STRASSE")
        assert result.normalized == "strasse"

    def test_preserves_numbers_and_punctuation(self):
        result = normalize_claim_text("The rate is 3.7%.")
        assert result.normalized == "the rate is 3.7%."


class TestHedgingRemoval:
    def test_remove_reportedly(self):
        result = normalize_claim_text("Reportedly, taxes increased.")
        assert result.normalized == "taxes increased."
        assert any("reportedly" in h for h in result.hedges_removed)

    def test_remove_allegedly(self):
        result = normalize_claim_text("He allegedly fled the country.")
        assert result.normalized == "he fled the country."
        assert any("allegedly" in h for h in result.hedges_removed)

    def test_remove_sources_say(self):
        result = normalize_claim_text("Sources say the rate is 5%.")
        assert result.normalized == "the rate is 5%."
        assert any("sources say" in h for h in result.hedges_removed)

    def test_remove_multiple_hedges(self):
        result = normalize_claim_text("Reportedly, allegedly, the senator lied.")
        assert result.normalized == "the senator lied."
        assert len(result.hedges_removed) >= 2

    def test_remove_purportedly(self):
        result = normalize_claim_text("He purportedly signed the bill.")
        assert result.normalized == "he signed the bill."

    def test_remove_apparently(self):
        result = normalize_claim_text("It SEEMS that APPARENTLY the vaccine is safe.")
        # "apparently" is removed; "seems" is not in the lexicon
        assert "apparently" not in result.normalized
        assert result.normalized == "it seems that the vaccine is safe."

    def test_remove_seemingly(self):
        result = normalize_claim_text("The policy seemingly reduced crime.")
        assert result.normalized == "the policy reduced crime."

    def test_remove_according_to_sources(self):
        result = normalize_claim_text("According to sources, the plan failed.")
        assert result.normalized == "the plan failed."

    def test_remove_it_is_claimed_that(self):
        result = normalize_claim_text("It is claimed that taxes doubled.")
        assert result.normalized == "taxes doubled."

    def test_remove_some_say(self):
        result = normalize_claim_text("Some say the economy is failing.")
        assert result.normalized == "the economy is failing."

    def test_remove_unconfirmed_reports_say(self):
        result = normalize_claim_text("Unconfirmed reports say the deal is off.")
        assert result.normalized == "the deal is off."

    def test_remove_unconfirmed_reports_suggest(self):
        result = normalize_claim_text("Unconfirmed reports suggest fraud occurred.")
        assert result.normalized == "fraud occurred."

    def test_no_hedges_present(self):
        result = normalize_claim_text("The unemployment rate is 3.7%.")
        assert result.normalized == "the unemployment rate is 3.7%."
        assert result.hedges_removed == []

    @pytest.mark.parametrize(
        "hedge",
        [
            "reportedly",
            "allegedly",
            "purportedly",
            "apparently",
            "seemingly",
        ],
    )
    def test_single_word_hedges_parametrized(self, hedge):
        text = f"The senator {hedge} took bribes."
        result = normalize_claim_text(text)
        assert hedge not in result.normalized
        assert len(result.hedges_removed) >= 1


class TestPronounResolution:
    def test_single_person_he(self):
        result = normalize_claim_text("he signed the bill", entity_persons=["Biden"])
        assert result.normalized == "biden signed the bill"
        assert result.pronouns_resolved is True

    def test_single_person_she(self):
        result = normalize_claim_text("she won the election", entity_persons=["Harris"])
        assert result.normalized == "harris won the election"
        assert result.pronouns_resolved is True

    def test_multiple_persons_skip(self):
        result = normalize_claim_text("he signed the bill", entity_persons=["Biden", "Obama"])
        assert result.normalized == "he signed the bill"
        assert result.pronouns_resolved is False

    def test_single_org_it(self):
        result = normalize_claim_text("it posted record profits", entity_orgs=["Apple"])
        assert result.normalized == "apple posted record profits"
        assert result.pronouns_resolved is True

    def test_no_entity_context(self):
        result = normalize_claim_text("he signed the bill")
        assert result.normalized == "he signed the bill"
        assert result.pronouns_resolved is False

    def test_they_single_person(self):
        result = normalize_claim_text("they signed the bill", entity_persons=["Biden"])
        assert result.normalized == "biden signed the bill"
        assert result.pronouns_resolved is True

    def test_they_single_org(self):
        result = normalize_claim_text("they posted profits", entity_orgs=["Apple"])
        assert result.normalized == "apple posted profits"
        assert result.pronouns_resolved is True

    def test_they_ambiguous_person_and_org(self):
        result = normalize_claim_text(
            "they raised taxes",
            entity_persons=["Biden"],
            entity_orgs=["Congress"],
        )
        # "they" not resolved because both person and org present
        assert result.normalized == "they raised taxes"


class TestWhitespaceAndArtifacts:
    def test_whitespace_collapse(self):
        result = normalize_claim_text("biden   signed   it")
        assert result.normalized == "biden signed it"

    def test_punctuation_artifact_double_comma(self):
        """Double comma from hedge removal: ', ,' -> ','."""
        result = normalize_claim_text("biden, , signed it")
        assert result.normalized == "biden, signed it"

    def test_space_before_comma_preserved(self):
        """Single comma with leading space is not an artifact — just whitespace collapse."""
        result = normalize_claim_text("biden ,  signed it")
        assert result.normalized == "biden , signed it"

    def test_leading_comma_after_hedge_removal(self):
        result = normalize_claim_text("Reportedly, Biden signed it.")
        # After removing "reportedly" we get ", biden signed it."
        assert not result.normalized.startswith(",")

    def test_tabs_and_newlines(self):
        result = normalize_claim_text("biden\tsigned\nthe order")
        assert result.normalized == "biden signed the order"


class TestEdgeCases:
    def test_empty_result_fallback(self):
        result = normalize_claim_text("reportedly allegedly")
        assert result.fallback_used is True
        assert result.normalized == "reportedly allegedly"

    def test_text_exceeding_200_chars(self):
        long_text = "the government " + "increased spending on " * 15 + "defense."
        result = normalize_claim_text(long_text)
        assert len(result.normalized) <= MAX_NORMALIZED_LENGTH
        assert result.normalized.endswith("...")

    def test_text_exactly_200_chars_no_truncation(self):
        text = "a" * 200
        result = normalize_claim_text(text)
        assert len(result.normalized) == 200
        assert not result.normalized.endswith("...")

    def test_pure_function_no_side_effects(self):
        """Calling normalize twice with same input produces same output."""
        r1 = normalize_claim_text("Reportedly, Biden signed it.", entity_persons=["Biden"])
        r2 = normalize_claim_text("Reportedly, Biden signed it.", entity_persons=["Biden"])
        assert r1.normalized == r2.normalized
        assert r1.hedges_removed == r2.hedges_removed
        assert r1.pronouns_resolved == r2.pronouns_resolved

    def test_result_type(self):
        result = normalize_claim_text("test claim")
        assert isinstance(result, NormalizeResult)
