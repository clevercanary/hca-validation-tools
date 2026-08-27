"""The uns key names our tooling owns.

The two halves of ``uns/provenance/edit_history``, named together because they
are one path. They live in a leaf module with no imports so that naming them
costs nothing: ``_io`` holds the four accessors that create and read the path,
``write`` builds the log entries, and ``schema.helpers`` needs the group name
to derive which roots are not the producer's — and none of those has to take on
another module's dependencies to agree with the others about a string.

That mattered concretely: before these were named, ``set_producer_uns``'s
pre-flight checked one spelling while ``ensure_provenance_group`` created
another, and ``has_edit_log_operation`` read a third. Renaming the group would
have left each of them quietly looking at a key nobody wrote (#631).
"""

PROVENANCE_KEY = "provenance"
EDIT_LOG_KEY = "edit_history"

# The shared tail of every masked-string refusal — the write funnel, the
# h5py normalization pass, and whatever masked-refusal site comes next
# compose it, so the wording cannot drift and the skills' claim that masked
# values "refuse by name everywhere" stays one sentence, not several.
MASKED_STRING_REMEDY = (
    "masked (null) string value(s), which have no plain-string "
    "representation — flattening would fabricate text for missing data; "
    "repair the values upstream first"
)
