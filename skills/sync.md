---
name: armada-sync
description: Pull knowledge changes from upstream sources and disposition them.
version: 0.1.0
source:
  repo: megadoomer-io/armada
  path: skills/sync.md
---

# /armada-sync — Pull Knowledge from Upstreams

Fetches changes from each configured upstream, runs the structural pre-filter
to skip trivial changes, then presents meaningful deltas for disposition.

## Workflow

### Step 1: Load config and state

```python
import armada.models.config as config
cfg = config.ArmadaConfig.load()
```

If config doesn't exist, tell the user to run `/armada setup` and stop.

### Step 2: For each upstream

Upstreams are members flagged `pull: true` (independent of group membership —
a friend can be pull-capable without being in a convergence group). The member
name is the dict key:

```
for name, upstream in cfg.pull_members.items():
```

#### 2a. Fetch latest

```python
import armada.git.cache as cache
clone = cache.CacheClone(name, upstream.repo)
clone.ensure()  # clone if missing, fetch if exists
current_rev = clone.head_rev()
```

#### 2b. Load grain state

```python
import armada.models.grain as grain
sgf = grain.SourceGrainFile.load(name)
```

If `sgf.last_reviewed_rev` is None, this is the first sync (onboarding).
Skip the structural pre-filter and run a full LLM comparison instead
(Step 3).

#### 2c. Check for changes

```python
if sgf.last_reviewed_rev == current_rev:
    # No changes since last sync, skip this upstream
    continue
```

#### 2d. Structural pre-filter

```python
import armada.git.filter as filter
changes = filter.structural_pre_filter(
    clone,
    sgf.last_reviewed_rev,
    paths=upstream.paths or None,
)
# (upstream is the Member; name is its dict key from the loop above)
```

Report what was filtered:

```
james: 8 files changed
  2 rename-only (skipped)
  1 whitespace-only (skipped)
  3 new files
  2 content changes
```

#### 2e. LLM semantic analysis (for content deltas and new files)

For each change with `kind == CONTENT_DELTA` or `kind == NEW_FILE`:

Read the file content from the cache clone:

```python
content = clone.show_file(change.path)
```

Ask the LLM to analyze the change. The prompt should include:
- The source file content
- The user's existing related instructions (if any local_paths exist for this grain)
- The question: "What is this knowledge? Is it something the user would benefit from? Summarize in 1-2 sentences."

The LLM assigns a `semantic_id` for new grains. For existing grains
(matched by semantic_id in the grain state), it evaluates the delta.

#### 2f. Present for disposition

For each significant change, use the disposition engine:

```python
import armada.disposition.engine as disposition

ctx = disposition.DispositionContext(
    mode=disposition.DispositionMode.UPSTREAM,
    source_name=name,
    grain_id=semantic_id,
    grain_description=llm_summary,
    source_content=content,
    local_content=local_content,
    diff_summary=diff_summary,
    source_paths=[change.path],
)
pres = disposition.build_presentation(ctx)
```

Present the `pres.header`, `pres.body`, and `pres.options` to the user.
Wait for their decision.

#### 2g. Apply decision

```python
disposition.apply_decision(
    sgf,
    grain_id=semantic_id,
    decision=user_decision,
    description=llm_summary,
    source_paths=[change.path],
    local_paths=local_paths,  # set if user chose Include
    notes=user_notes,         # optional
    exclude_until=exclude_until,  # if Exclude
)
```

For **Include** decisions:
- Ask the LLM to adapt the source content to the user's repo structure
  and conventions (respecting `cfg.preferences` for tool-specific adapters)
- Present the adapted content for approval
- If approved, write to the user's agent instructions repo and commit
- **Ask the user which audiences to share this grain with** (group names, or
  `"*"` for all groups). Store on `grain.audiences`. Leaving it empty keeps the
  grain private — it is included locally but proposed to no one. Sharing is
  opt-in; absence never means broadcast.

#### 2h. Update state

```python
sgf.current_rev = current_rev
sgf.last_reviewed_rev = current_rev
sgf.save()
```

### Step 3: First sync (onboarding)

When `last_reviewed_rev` is None, the structural pre-filter has no baseline.
Instead:

1. Read the upstream's full agent instruction set (all files matching
   `upstream.paths`, or the entire repo if no path filter)
2. Read the user's full agent instruction set (`cfg.identity.agent_root`)
3. Send both to the LLM with the prompt:

   > Read both instruction sets. Identify knowledge in the source that the
   > user doesn't have, knowledge the user has that differs from the source,
   > and knowledge that's equivalent. For each gap, assign a semantic_id
   > and write a 1-2 sentence description.

4. The LLM returns a list of grains with semantic IDs
5. Present each grain for disposition (same flow as 2f-2g)
6. Set `last_reviewed_rev = current_rev`

**Model recommendation**: Use a stronger model (Opus) for onboarding.
The first comparison needs accurate semantic grain identification across
two structurally different instruction sets.

### Step 4: Queue peer proposals

After processing all upstreams, for each grain that was **Included** and given a
non-empty `audiences`, queue it to the members those audiences resolve to. A
grain left private (`audiences == []`) is proposed to no one.

```python
import armada.models.queue as queue

eligible_members = {
    m
    for group_name in config.resolve_groups(grain.audiences, cfg)
    for m in cfg.groups[group_name].members
}
for member_name in sorted(eligible_members):
    # Skip if the member already has this grain (check their repo via cache clone).
    q = queue.ProposalQueue.load(member_name)
    q.pending_proposals.append(
        queue.PendingProposal(
            grain_id=grain.semantic_id,
            description=grain.description,
            estimated_value=queue.EstimatedValue.HIGH,
        )
    )
    q.save()
```

`resolve_groups` maps the grain's audiences to concrete groups (identity map
today; `"*"` expands to all groups; unknown names are dropped). Convergence and
downstream pushes are handled later by `/armada-propose`, not here.

## Error Handling

- **Git fetch failure**: Skip the source, report the error, continue with others
- **LLM timeout**: Skip the grain, report it, continue. The grain stays
  un-dispositioned and will be surfaced on the next sync.
- **Config missing**: Tell the user to run `/armada setup`

## Model Selection

- **Onboarding (first sync)**: Recommend Opus for accurate semantic grain ID
- **Incremental sync**: Sonnet is sufficient for evaluating known-grain deltas
- These are recommendations surfaced to the user, not enforced
