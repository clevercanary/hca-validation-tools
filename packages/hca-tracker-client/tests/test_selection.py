"""Atlas version selection: network and atlas are required, nothing is inferred."""

import pytest

from hca_tracker_client import SelectionError, atlas_version, find_file, select_atlas


def atlas(network, slug, generation, revision, published=False):
    return {
        "id": f"{network}-{slug}-{generation}.{revision}",
        "bioNetwork": network,
        "shortNameSlug": slug,
        "generation": generation,
        "revision": revision,
        "publishedAt": "2026-01-01" if published else None,
    }


ATLASES = [
    atlas("adipose", "adipose", 1, 0, published=True),
    atlas("lung", "adipose", 1, 0, published=True),
    atlas("lung", "adipose", 1, 1),
    atlas("lung", "adipose", 2, 0, published=True),
    atlas("lung", "adipose", 2, 1),
    atlas("gut", "gut", 1, 0),
]


def pick(**kwargs):
    return atlas_version(select_atlas(ATLASES, **kwargs))


@pytest.mark.parametrize(
    ("network", "slug", "missing"),
    [(None, "adipose", "network"), ("lung", None, "atlas"), ("", "", "network and atlas")],
)
def test_network_and_atlas_are_required(network, slug, missing):
    with pytest.raises(SelectionError, match=f"^{missing} must be given"):
        select_atlas(ATLASES, network, slug)


def test_slug_in_another_network_is_not_inferred():
    """``adipose`` alone matches two networks; each network is its own atlas."""
    assert select_atlas(ATLASES, "adipose", "adipose")["id"] == "adipose-adipose-1.0"
    assert pick(network="lung", atlas="adipose") == "v2.1"


def test_unknown_pair_lists_valid_pairs():
    with pytest.raises(SelectionError) as error:
        select_atlas(ATLASES, "gut", "adipose")
    assert str(error.value) == (
        "No atlas gut/adipose. Valid network/atlas pairs: adipose/adipose, gut/gut, lung/adipose"
    )


def test_newest_revision_of_highest_generation_by_default():
    assert pick(network="lung", atlas="adipose") == "v2.1"


def test_generation_picks_its_newest_revision():
    assert pick(network="lung", atlas="adipose", generation=1) == "v1.1"


def test_missing_generation_lists_generations():
    with pytest.raises(SelectionError, match=r"has no generation 3 \(generations: 1, 2\)"):
        select_atlas(ATLASES, "lung", "adipose", generation=3)


def test_published_picks_highest_published_version():
    assert pick(network="lung", atlas="adipose", published=True) == "v2.0"
    assert pick(network="lung", atlas="adipose", generation=1, published=True) == "v1.0"


def test_published_with_none_published():
    with pytest.raises(SelectionError, match="gut/gut has no published version$"):
        select_atlas(ATLASES, "gut", "gut", published=True)


def test_find_file_by_name_or_id():
    files = [{"fileId": "f1", "fileName": "a.h5ad"}, {"fileId": "f2", "fileName": "b.h5ad"}]
    assert find_file(files, "b.h5ad", "x")["fileId"] == "f2"
    assert find_file(files, "f1", "x")["fileName"] == "a.h5ad"
    with pytest.raises(SelectionError, match=r"No file 'c.h5ad' in gut/gut v1.0. Files: a.h5ad, b.h5ad"):
        find_file(files, "c.h5ad", "gut/gut v1.0")
