---
name: armada-review
description: Review and disposition incoming knowledge proposals from peers.
version: 0.1.0
source:
  repo: megadoomer-io/armada
  path: skills/review.md
---

# /armada-review — Handle Incoming Proposals

Finds and processes PRs that peers have opened on your agent instructions
repo via Armada.

## Workflow

### Step 1: Discover incoming proposals

Search for open PRs on the user's repo that were created by Armada:

1. **By branch prefix**: PRs with branches matching `armada/*/`
2. **By label**: PRs with the `armada` label (backup, in case branch
   was renamed)

```
# Using GitHub MCP or gh CLI:
# Search for PRs with armada branch prefix on user's repo
```

If no incoming proposals found, report "No incoming proposals" and stop.

### Step 2: For each incoming proposal

#### 2a. Read the PR

- Read the PR title, description, and changed files
- Extract the grain semantic_id from the PR description or branch name
- Read the proposed file content

#### 2b. Compare against local instructions

Check if the user already has related knowledge:

```python
import armada.models.config as config
cfg = config.ArmadaConfig.load()
```

Ask the LLM to compare:

> A peer proposes adding this knowledge to your instructions:
>
> {proposed_content}
>
> Your current related instructions (if any):
>
> {local_content}
>
> What does this add that you don't already have? Is it compatible
> with your existing approach? Summarize in 2-3 sentences.

#### 2c. Present for disposition

```python
import armada.disposition.engine as disposition

ctx = disposition.DispositionContext(
    mode=disposition.DispositionMode.PEER,
    source_name=pr_author,
    grain_id=semantic_id,
    grain_description=llm_comparison_summary,
    source_content=proposed_content,
    local_content=local_content,
)
pres = disposition.build_presentation(ctx)
```

Present to the user with the LLM's comparison analysis.

#### 2d. Act on decision

**Accept**:
1. Merge the PR (or approve it for the user to merge)
2. Update grain state with the accepted grain
3. Optionally ask which audiences to tag the now-included grain with (group
   names, or `"*"`), stored on `grain.audiences`, so it can be proposed onward
   on the next `/armada-sync`. Leave empty to keep it private (included locally,
   shared with no one) — sharing is opt-in.

**Modify**:
1. Present the proposed content for editing
2. User (or LLM with user guidance) adjusts the content
3. Push the modification to the PR branch
4. Merge the updated PR

**Decline**:
1. Close the PR with a comment explaining why
2. Record the decline in grain state so the proposer's system
   knows not to re-propose the same grain

### Step 3: Report results

```
Armada Review
─────────────
PR #42 from james: kdrift MCP integration
  → Accepted (merged)

PR #43 from james: verify-assumptions debugging
  → Deferred (will review later)
```

## Comment Format (on declined PRs)

```markdown
Declined via Armada review.

**Reason**: {user's reason or "Already have equivalent coverage"}

This decline is recorded in my Armada state, so this specific grain
won't be re-proposed unless it changes substantially.
```

## Error Handling

- **PR merge failure**: Report the error, suggest manual merge
- **PR close failure**: Report, suggest manual close
- **No GitHub access**: Report which PRs need review (titles + URLs)
  and let the user handle them manually
