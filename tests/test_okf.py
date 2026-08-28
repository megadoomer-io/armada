"""Tests for the OKF v0.2 grain wire-format serializers."""

import datetime
import textwrap

import yaml

import armada.models.config as config_mod
import armada.models.grain as grain_mod
import armada.okf as okf


def _convergence_cfg() -> config_mod.ArmadaConfig:
    return config_mod.ArmadaConfig.model_validate(
        yaml.safe_load(
            textwrap.dedent("""\
            version: 2
            identity: { name: mikedougherty, repo: mikedougherty/dotfiles }
            members:
              james: { repo: james/dotfiles }
              josh: { repo: josh/dotfiles }
            groups:
              coworkers:
                members: [james, josh]
                convergence: { threshold: 2, downstream: cpe }
            downstreams:
              cpe: { repo: missionlane-scratch/cpe }
            """)
        )
    )


def _sample_grain() -> grain_mod.GrainState:
    return grain_mod.GrainState(
        semantic_id="kustomize-patch-strategy",
        description="Prefer strategic-merge patches; JSON6902 only for list-item edits.",
        kind="knowledge",
        disposition=grain_mod.Disposition.INCLUDE,
        disposition_date=datetime.date(2026, 8, 20),
        audiences=["coworkers"],
        source_paths=["cerebral/engineering/knowledge/kustomize/KNOWLEDGE.md"],
        local_paths=[".agents/knowledge/kustomize/KNOWLEDGE.md"],
        notes="Adopted after the W34 overlay-fold discussion.",
        exclude_until=None,
        proposed_to=[
            grain_mod.GrainProposal(
                target="james",
                group="coworkers",
                status=grain_mod.ProposalStatus.ACCEPTED,
                accepted_at=datetime.date(2026, 8, 22),
            ),
            grain_mod.GrainProposal(
                target="josh",
                group="coworkers",
                pr_number=42,
                pr_url="https://github.com/x/y/pull/42",
                status=grain_mod.ProposalStatus.PENDING,  # must NOT travel
            ),
        ],
    )


def test_round_trip_preserves_mapped_fields() -> None:
    grain = _sample_grain()
    text = okf.to_okf(
        grain,
        generated_by="human:mikedougherty",
        generated_at=datetime.date(2026, 8, 18),
        body="# Patch strategy\n\nUse strategic-merge by default.",
    )
    parsed = okf.from_okf(text)
    out = parsed.grain

    assert out.semantic_id == grain.semantic_id
    assert out.description == grain.description
    assert out.kind == grain.kind
    assert out.disposition == grain.disposition
    assert out.disposition_date == grain.disposition_date
    assert out.audiences == grain.audiences
    assert out.source_paths == grain.source_paths
    assert out.local_paths == grain.local_paths
    assert out.notes == grain.notes
    assert parsed.generated_by == "human:mikedougherty"
    assert parsed.generated_at == datetime.date(2026, 8, 18)
    assert "Use strategic-merge by default." in parsed.body


def test_type_grain_and_kind_extension() -> None:
    text = okf.to_okf(_sample_grain(), generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["type"] == "Grain"  # OKF concept kind
    assert fm["kind"] == "knowledge"  # our extension, the grain's nature


def test_only_accepted_proposals_travel() -> None:
    text = okf.to_okf(_sample_grain(), generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    fm = yaml.safe_load(text.split("---", 2)[1])
    # james accepted; josh pending. Only james becomes a verified entry.
    assert len(fm["verified"]) == 1
    entry = fm["verified"][0]
    assert entry["by"] == "human:james"
    assert entry["group"] == "coworkers"  # D3=a: per-entry group
    assert entry["at"] == "2026-08-22T00:00:00Z"


def test_timestamps_are_quoted_rfc3339_strings() -> None:
    text = okf.to_okf(_sample_grain(), generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    fm = yaml.safe_load(text.split("---", 2)[1])
    # If unquoted, YAML would parse these into datetime objects; they must stay str.
    assert isinstance(fm["generated"]["at"], str)
    assert fm["generated"]["at"] == "2026-08-18T00:00:00Z"
    assert isinstance(fm["verified"][0]["at"], str)


def test_accepted_proposals_reconstruct_from_verified() -> None:
    text = okf.to_okf(_sample_grain(), generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    parsed = okf.from_okf(text)
    accepted = parsed.grain.proposed_to
    assert len(accepted) == 1
    assert accepted[0].target == "james"
    assert accepted[0].group == "coworkers"
    assert accepted[0].status is grain_mod.ProposalStatus.ACCEPTED
    assert accepted[0].accepted_at == datetime.date(2026, 8, 22)


def test_output_is_structurally_conformant() -> None:
    text = okf.to_okf(_sample_grain(), generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    assert text.startswith("---\n")
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm.get("type")  # §11: non-empty type is the one hard requirement
    assert fm["semantic_id"]  # D1: canonical identity present


def test_wire_projection_drops_sender_local_fields() -> None:
    """The wire projection (include_local=False) is what travels in a proposal:
    shared knowledge + provenance + trust, but none of the sender's local ledger."""
    text = okf.to_okf(
        _sample_grain(),
        generated_by="human:mikedougherty",
        generated_at=datetime.date(2026, 8, 18),
        include_local=False,
    )
    fm = yaml.safe_load(text.split("---", 2)[1])
    # Shared knowledge + provenance + trust travel:
    assert fm["type"] == "Grain"
    assert fm["kind"] == "knowledge"
    assert fm["description"]
    assert fm["semantic_id"] == "kustomize-patch-strategy"
    assert fm["generated"]["by"] == "human:mikedougherty"
    assert fm["verified"][0]["by"] == "human:james"  # convergence still travels
    assert fm["sources"][0]["resource"]
    # Sender-local ledger does NOT travel:
    for local in ("disposition", "disposition_date", "audiences", "exclude_until", "local_paths", "notes"):
        assert local not in fm, f"{local} must not travel in the wire projection"


def test_wire_projection_still_conformant_and_round_trips() -> None:
    text = okf.to_okf(
        _sample_grain(),
        generated_by="human:me",
        generated_at=datetime.date(2026, 8, 18),
        include_local=False,
    )
    parsed = okf.from_okf(text)
    assert parsed.grain.semantic_id == "kustomize-patch-strategy"
    assert parsed.grain.kind == "knowledge"
    # accepted proposal (convergence) survived; local fields are absent/empty
    assert len(parsed.grain.proposed_to) == 1
    assert parsed.grain.disposition is None
    assert parsed.grain.audiences == []


def test_trust_tier_derives_from_accepts() -> None:
    g = grain_mod.GrainState(semantic_id="x")
    assert okf.trust_tier(g) == okf.TRUST_UNVERIFIED
    g.proposed_to.append(
        grain_mod.GrainProposal(
            target="james", group="coworkers", status=grain_mod.ProposalStatus.ACCEPTED
        )
    )
    assert okf.trust_tier(g) == okf.TRUST_HUMAN_REVIEWED


def test_convergence_view_equals_verified_entries() -> None:
    """The OKF trust view and armada convergence read the same signal: verified[] entries
    tagged with a group ARE that group's accept count toward its threshold."""
    cfg = _convergence_cfg()
    g = grain_mod.GrainState(
        semantic_id="kustomize-patch-strategy",
        audiences=["coworkers"],
        proposed_to=[
            grain_mod.GrainProposal(target="james", group="coworkers", status=grain_mod.ProposalStatus.ACCEPTED),
            grain_mod.GrainProposal(target="josh", group="coworkers", status=grain_mod.ProposalStatus.ACCEPTED),
        ],
    )
    view = okf.convergence_view(g, cfg)
    assert len(view) == 1
    gv = view[0]
    assert (gv.group, gv.accepts, gv.threshold, gv.converged) == ("coworkers", 2, 2, True)

    # Equivalence: coworkers-tagged verified[] entries in the OKF output == accepts.
    text = okf.to_okf(g, generated_by="human:me", generated_at=datetime.date(2026, 8, 18))
    fm = yaml.safe_load(text.split("---", 2)[1])
    coworker_verified = [v for v in fm["verified"] if v.get("group") == "coworkers"]
    assert len(coworker_verified) == gv.accepts


def test_export_bundle_writes_conformant_bundle(tmp_path) -> None:
    grains = [
        grain_mod.GrainState(semantic_id="kustomize-patch-strategy", description="Patch strategy", kind="knowledge"),
        grain_mod.GrainState(semantic_id="verify-assumptions", description="Verify before acting", kind="rule"),
    ]
    out = okf.export_bundle(
        grains,
        tmp_path / "bundle",
        generated_by="human:mikedougherty",
        generated_at=datetime.date(2026, 8, 18),
        bodies={"kustomize-patch-strategy": "# Patch strategy\n\nStrategic-merge by default."},
    )
    assert (out / "index.md").exists()
    assert (out / "grains" / "kustomize-patch-strategy.md").exists()
    assert (out / "grains" / "verify-assumptions.md").exists()

    index = (out / "index.md").read_text()
    assert 'okf_version: "0.2"' in index
    assert "grains/kustomize-patch-strategy.md" in index
    assert "grains/verify-assumptions.md" in index

    parsed = okf.from_okf((out / "grains" / "kustomize-patch-strategy.md").read_text())
    assert parsed.grain.semantic_id == "kustomize-patch-strategy"
    assert "Strategic-merge by default." in parsed.body
