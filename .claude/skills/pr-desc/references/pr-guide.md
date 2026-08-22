# PR Description Guide

## When to write one
Every PR that merges a feature, bug fix, or enhancement should have a description. Version bump PRs can be minimal.

## Format
```
### Changes
* <what changed and why, one bullet per logical change>

Closes #<branch number, ex. for 279-Bug, it would be Closes #279>
```

## Tips
- VERY IMPORTANT:Don't forget the "Closes #" at the end 
- One bullet per ticket/branch merged
- Keep bullets short — lead with the action (Fixed, Added, Updated, Removed)
- Mention the command, file, or system affected if it adds clarity
- No overviews or extra context — that belongs in the release notes
- The only header beyond `### Changes` is `### Notes`, used rarely and only when a reviewer must know a deferred item, spec deviation, or caveat. Default to omitting it.
