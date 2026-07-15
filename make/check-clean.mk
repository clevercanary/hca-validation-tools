# Shared `check-clean` guard, included by the service Makefiles that publish a
# container image (dataset-validator Batch, entry-sheet-validator Lambda). Each
# includer defines its own TAG (defaulting to the HEAD short SHA).
#
# Refuses to publish an image whose tag would misdescribe its contents. `docker
# build` copies from the working tree, but TAG defaults to the HEAD commit — so a
# dirty tree produces an image tagged with a commit that does not contain what is
# inside it, and checking out that SHA rebuilds something different.
#
# Three things below are load-bearing and look optional:
#
#   --untracked-files=all   `git status` honours status.showUntrackedFiles; a user
#                           who set it to `no` would get an empty listing and the
#                           guard would pass while shipping untracked files.
#
#   exit-status check       A bare `$(git status)` substitution is empty when git
#                           errors, and empty reads as clean — failing open in
#                           exactly the cases where provenance is unverifiable.
#
#   no TAG exemption        A hand-picked tag does not make unreproducible content
#                           acceptable, and exempting it would quietly become the
#                           override flag this guard is designed not to have.
#
# .dockerignore excludes *ignored* artifacts from the context, which is what makes
# `git status` a sufficient test — but it does not make this guard redundant: an
# untracked, non-ignored file reaches the image and git flags it `??`.
.PHONY: check-clean
check-clean:
	@if ! git rev-parse --git-dir >/dev/null 2>&1; then \
		echo "Error: not a git repository, so the tree cannot be verified."; \
		echo "  Refusing to publish an image whose provenance cannot be established."; \
		exit 1; \
	fi; \
	dirty=$$(git status --porcelain --untracked-files=all) || { \
		echo "Error: 'git status' failed, so the tree cannot be verified."; \
		echo "  Refusing to publish an image whose provenance cannot be established."; \
		exit 1; \
	}; \
	if [ -n "$$dirty" ]; then \
		echo "Error: refusing to publish from a dirty working tree."; \
		echo ""; \
		echo "  The image would contain these uncommitted changes, but be published"; \
		echo "  as :$(TAG), which does not have them. The tag would be a lie."; \
		echo ""; \
		printf '%s\n' "$$dirty" | sed 's/^/    /'; \
		echo ""; \
		echo "  Commit and merge first, then rebuild."; \
		exit 1; \
	fi
