#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <student-repository> <student-commit>" >&2
    exit 2
fi

script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
student_repository=$1
student_ref=$2
upstream_repository=${UPSTREAM_REPOSITORY:-"$script_directory/../spring-seminar-upstream"}
upstream_ref=${UPSTREAM_REF:-HEAD}
work_directory=$(mktemp -d)
container_name="seminar-judge-$$-$RANDOM"

cleanup() {
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    rm -rf -- "$work_directory"
}
trap cleanup EXIT

git clone --quiet --no-checkout "$upstream_repository" "$work_directory/upstream-repository"
git clone --quiet --no-checkout "$student_repository" "$work_directory/student-repository"

upstream_commit=$(git -C "$work_directory/upstream-repository" rev-parse --verify "$upstream_ref^{commit}")
student_commit=$(git -C "$work_directory/student-repository" rev-parse --verify "$student_ref^{commit}")
grading_directory="$work_directory/grading"
mkdir "$grading_directory"

git -C "$work_directory/upstream-repository" archive "$upstream_commit" | tar -x -C "$grading_directory"
cp "$script_directory/docker-entrypoint.sh" "$grading_directory/.judge-entrypoint.sh"

runner_hash=$(sha256sum "$script_directory/Dockerfile" "$script_directory/docker-entrypoint.sh" | sha256sum | cut -c1-12)
image="spring-seminar-judge:${upstream_commit:0:12}-$runner_hash"
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build --quiet --tag "$image" --file "$script_directory/Dockerfile" "$grading_directory"
fi

mv "$grading_directory/src/main" "$work_directory/upstream-main"
git -C "$work_directory/student-repository" archive "$student_commit" src/main | tar -x -C "$grading_directory"

echo "grading student commit $student_commit with upstream commit $upstream_commit"

# ponytail: the per-run workspace is writable; precompile and remount test classes read-only if adversarial submissions become a concern.
if timeout --kill-after=5s 180s docker run --rm \
    --name "$container_name" \
    --network none \
    --memory 1g \
    --cpus 1 \
    --pids-limit 256 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --read-only \
    --tmpfs /tmp:rw,nosuid,size=1g \
    --volume /home/grader/.gradle \
    --volume /home/grader/.kotlin \
    --volume "$grading_directory:/submission:ro" \
    "$image"; then
    echo "PASSED"
else
    status=$?
    echo "FAILED" >&2
    exit "$status"
fi
