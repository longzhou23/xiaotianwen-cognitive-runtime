import pytest

from iris_memory.cognitive.contracts import (
    CanonicalEntity,
    CognitiveContractError,
    IdentityClaim,
    IdentityClaimStatus,
    IdentityConfig,
    Perspective,
)
from iris_memory.cognitive.identity import EntityRegistry, IdentityResolver
from iris_memory.cognitive.perspective import PerspectiveResolver


def test_uid_is_stable_when_display_name_changes():
    resolver = IdentityResolver(EntityRegistry())

    first = resolver.resolve_actor("qq", "10001", "龙洲")
    renamed = resolver.resolve_actor("qq", "10001", "longz")

    assert first is not None
    assert first.entity_id == "person:qq:10001"
    assert renamed == first


def test_same_display_name_stays_distinct_for_different_uids():
    resolver = IdentityResolver(EntityRegistry())

    first = resolver.resolve_actor("qq", "10001", "龙洲")
    second = resolver.resolve_actor("qq", "10002", "龙洲")

    assert first is not None
    assert second is not None
    assert first.entity_id == "person:qq:10001"
    assert second.entity_id == "person:qq:10002"
    assert first != second


def test_platform_binding_normalizes_case_and_does_not_merge_platforms():
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity("person:qq-user", platform_ids={" QQ ": "10001"}),
        source="test",
    )

    qq = registry.resolve_platform_id("qq", "10001")
    onebot = registry.resolve_platform_id("onebot", "10001")

    assert qq is not None
    assert onebot is not None
    assert qq.entity_id == "person:qq-user"
    assert onebot.entity_id == "person:onebot:10001"
    assert qq.entity_id != onebot.entity_id


def test_conflicting_platform_binding_is_rejected_before_it_can_resolve():
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity("person:first", platform_ids={"qq": "10001"}),
        source="test",
    )

    with pytest.raises(CognitiveContractError, match="platform identity already belongs"):
        registry.register_entity(
            CanonicalEntity("person:second", platform_ids={"QQ": "10001"}),
            source="test",
        )


def test_confirmed_alias_resolves_and_revocation_rolls_it_back():
    registry = EntityRegistry()
    registry.register_entity(CanonicalEntity("person:longz"), source="test")
    claim = IdentityClaim(
        mention="龙洲",
        candidate_entity="person:longz",
        evidence=("manual confirmed test fixture",),
        confidence=1.0,
        source="test",
        status=IdentityClaimStatus.CONFIRMED,
    )
    registry.add_claim(claim)

    assert registry.resolve_alias("龙洲").entity_id == "person:longz"
    assert registry.revoke_claim(claim).status is IdentityClaimStatus.REVOKED
    assert registry.resolve_alias("龙洲") is None


def test_confirmed_alias_with_two_entities_stays_unresolved():
    registry = EntityRegistry()
    for entity_id in ("person:first", "person:second"):
        registry.register_entity(CanonicalEntity(entity_id), source="test")
        registry.add_claim(
            IdentityClaim(
                mention="龙洲",
                candidate_entity=entity_id,
                evidence=("conflicting imported alias",),
                confidence=1.0,
                source="test",
                status=IdentityClaimStatus.CONFIRMED,
            )
        )

    assert registry.resolve_alias("龙洲") is None


def test_possible_alias_never_merges_and_coreference_stays_conservative():
    registry = EntityRegistry()
    registry.register_entity(CanonicalEntity("person:longz"), source="test")
    registry.add_claim(
        IdentityClaim(
            mention="龙妹",
            candidate_entity="person:longz",
            evidence=("unverified chat guess",),
            confidence=0.4,
            source="test",
            status=IdentityClaimStatus.POSSIBLE,
        )
    )

    actor = registry.resolve_platform_id("qq", "10001")
    assert registry.resolve_alias("龙妹") is None
    assert registry.resolve_coreference("我", actor=actor).entity_id == actor.entity_id
    assert registry.resolve_coreference("他", actor=actor) is None


def test_self_binding_projects_only_confirmed_self_memories():
    config = IdentityConfig()
    registry = EntityRegistry(config)
    perspective = PerspectiveResolver(config)
    self_ref = registry.resolve_alias("小天文")

    assert self_ref is not None
    assert perspective.resolve(self_ref) is Perspective.AUTOBIOGRAPHICAL
    # Runtime projection is structured framing; raw memory content is never
    # rewritten inside the sentence.
    assert perspective.project("小天文曾经和 NICEICK 玩梗", Perspective.AUTOBIOGRAPHICAL) == "小天文曾经和 NICEICK 玩梗"
    assert perspective.project("小天文学会曾经组织观测", Perspective.AUTOBIOGRAPHICAL) == "小天文学会曾经组织观测"
    assert perspective.project("小天文爱好者曾经参与观测", Perspective.AUTOBIOGRAPHICAL) == "小天文爱好者曾经参与观测"
    assert perspective.project("小天文台昨晚开放", Perspective.AUTOBIOGRAPHICAL) == "小天文台昨晚开放"
    assert perspective.project("小天文望远镜该选哪种", Perspective.AUTOBIOGRAPHICAL) == "小天文望远镜该选哪种"
    assert perspective.project("小天文知识竞赛", Perspective.AUTOBIOGRAPHICAL) == "小天文知识竞赛"
    assert perspective.project("助手曾经和 NICEICK 玩梗", Perspective.UNRESOLVED) == "助手曾经和 NICEICK 玩梗"


def test_restart_keeps_deterministic_uid_and_self_but_not_unpersisted_alias_claim():
    before_restart = EntityRegistry()
    actor = before_restart.resolve_platform_id("qq", "10001")
    assert actor is not None
    before_restart.add_claim(
        IdentityClaim(
            mention="龙洲",
            candidate_entity=actor.entity_id,
            evidence=("confirmed runtime-only test claim",),
            confidence=1.0,
            source="test",
            status=IdentityClaimStatus.CONFIRMED,
        )
    )
    assert before_restart.resolve_alias("龙洲").entity_id == actor.entity_id

    after_restart = EntityRegistry()

    assert after_restart.resolve_alias("龙洲") is None
    assert after_restart.resolve_platform_id("qq", "10001").entity_id == actor.entity_id
    assert after_restart.resolve_alias("小天文").entity_id == "agent:xiaotianwen"
