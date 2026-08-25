# Guarded merge and exact merge-commit validation

Generate repository- and head-pinned commands with:

```python
render_guarded_merge_commands("owner/private-repository", PR_NUMBER, REVIEWED_HEAD)
render_post_merge_validation("owner/private-repository", PR_NUMBER, REVIEWED_HEAD)
```

The generated preflight verifies private visibility, OPEN and non-Draft PR
state, `main` base, exact head, CLEAN merge state, and required checks. The only
generated merge operation is:

```text
gh pr merge PR_NUMBER --repo owner/private-repository --merge --match-head-commit FULL_HEAD_SHA
```

The post-merge commands independently read the merge commit, fetch remote
`main`, prove the reviewed head is an ancestor of the exact merge commit, prove
both commits are ancestors of remote `main`, and require a two-parent merge
commit. The validator never executes these commands itself.
