# Guarded merge and exact merge-commit validation

Generate repository- and head-pinned commands with:

```python
render_guarded_merge_commands("owner/private-repository", PR_NUMBER, REVIEWED_HEAD)
render_post_merge_validation("owner/private-repository", PR_NUMBER, REVIEWED_HEAD)
```

The generated preflight verifies private visibility, OPEN and non-Draft PR
state, `main` base, exact head, and a closed review state before considering
mergeability. A merge requires all of the following:

- zero pending user or team review requests;
- zero `CHANGES_REQUESTED` reviews;
- a pagination-complete review-thread inventory with zero unresolved threads;
- CLEAN merge state; and
- every ruleset-required status check successful.

`COMMENTED` reviews are permitted only after every associated thread is
triaged and resolved. Informational/style threads may be resolved with an
evidence-backed reply. Any substantive security, correctness, oracle, or policy
thread requires a corrective commit and re-review; it must never be resolved as
an administrative bypass.

The only generated merge operation is:

```text
gh pr merge PR_NUMBER --repo owner/private-repository --merge --match-head-commit FULL_HEAD_SHA
```

The post-merge commands independently read the merge commit, fetch remote
`main`, prove the reviewed head is an ancestor of the exact merge commit, prove
both commits are ancestors of remote `main`, and require a two-parent merge
commit. The validator never executes these commands itself.
