# PR Bottleneck Risk Predictor

Predicts, for an open pull request on GitHub, the probability it will merge
within a given time window — checked at several checkpoints (1, 3, 7, 15, and
30 days after it was opened). The goal is to flag PRs that are at elevated
risk of stalling, early enough that a maintainer can actually do something
about it.

## Problem framing

This is a **multi-checkpoint binary classification** problem, not a single
prediction. For each PR, at each checkpoint it's still open at, the question
asked is: *will this merge before the next checkpoint?* A PR that merges
quickly contributes only one or two rows to the training data; a PR that
lingers contributes one row per checkpoint it survives. This "long format" —
one row per PR per checkpoint — is what the whole pipeline is built around.

## Data pipeline

### 1. Repo discovery
Candidate repos are pulled via GitHub's Search API, filtered for genuine
merge history, not being a fork, and recent activity. The star-count range
was deliberately widened to mix large, well-known projects with smaller/
mid-size ones, rather than only sampling the giants.

### 2. Pull request collection
A GraphQL fetcher pulls full PR history per repo — metadata, timestamps,
author info, labels, and comment/review counts — with rate-limit handling,
a per-repo cap (some repos have tens of thousands of PRs), and checkpointed
resume so a crash mid-fetch doesn't lose hours of progress.

### 3. Auditing and exclusion — the most important phase
Raw "looks like a PR-generating repo" and "actually behaves like one the way
the model expects" turned out to be very different things. Auditing (author
composition, merge-speed distributions, bot-vs-human breakdowns) surfaced
several non-obvious problems, each confirmed individually before excluding:

- Repos dominated by an internal sync bot mirroring work done elsewhere,
  not organic GitHub-native review activity
- Major projects (e.g. Spark, Go, PyTorch) that merge through their own
  tooling instead of GitHub's merge button, making GitHub's own "merged"
  signal unreliable or absent even though real development is happening
- Curated lists, curriculum content, and config bundles — same surface
  shape as a maintained library, completely different underlying activity
- Legacy repos that barely clear the bar for "recently active"

Nothing gets deleted. A **flag-don't-delete** design is used throughout:
one exclusion-reason field at the repo level, one at the individual-PR level
(bot-authored, draft, WIP-labeled). "Give me only the eligible data" is then
just a filter on those two fields, applied consistently everywhere
downstream. After this phase, roughly 63% of collected PRs remain eligible.

### 4. Comment/review timelines
The original fetch only captured comment/review *counts*, not timestamps —
which meant "how many comments existed by day 3" couldn't be computed. A
second, targeted fetch pulls full comment/review timelines, but only for
PRs that survived cleaning. Any PR number GitHub fails to resolve mid-fetch
is tracked explicitly (not silently recorded as "zero activity"), and cross-
checked against the original comment/review *counts* to catch cases where
that distinction matters.

## Snapshot and label generation

For each eligible PR, one row is generated per checkpoint it was still open
at, stopping as soon as the PR resolves (merges or closes without merging).

- **Features** on each row reflect only what was knowable as of that
  checkpoint — nothing computed from the PR's future.
- **Label** is whether the PR merged before the *next* checkpoint, not
  whether it eventually merged at all.
- **Still-open PRs** (never resolved as of when the data was pulled) get a
  row for every checkpoint they'd actually reached by that point, with the
  label left blank on the final row rather than guessed — the outcome
  genuinely isn't known yet, and treating it as "no" would be quietly wrong.
- **Partial observability** is respected too: if a repo was scraped before
  a PR had even reached day 15, no day-15 row is generated for it, since
  that day hadn't happened yet from the data's point of view.

## Features

**Static** (fixed at PR creation, same across all of that PR's rows):
diff size and files changed (normalized to each repo's own median, not
pooled across repos of very different scale), title length, label count,
day of week / hour opened, and author/repo historical stats — the author's
and the repo's own prior PR count and prior merge rate, computed so that a
past PR only counts toward "resolved" once its outcome had actually
happened as of the current PR's creation time. A past PR that was still
open at that point doesn't get credited with an outcome the data didn't
know yet — getting this wrong would have quietly leaked future information
into a feature that's supposed to be knowable only from history.

**Dynamic** (recomputed at each checkpoint): comments and reviews so far,
a "reviewer assigned" proxy (at least one review submitted by that
checkpoint — not literal assignment, since reviewer identity itself was
never fetched), and first-response latency.

## Modeling

- PRs are subsampled by whole repo (not by row) to keep experimentation
  fast, and split so that held-out test repos are never seen in training —
  a repo's rows never land on both sides of the split.
- Class imbalance is handled with either SMOTE or `class_weight`/
  `scale_pos_weight`, treated as alternatives to compare, not combined.
- A broad benchmark across roughly 30 classifiers narrows the field;
  focused tuning (via randomized hyperparameter search, with the *inner*
  cross-validation also grouped by repo) is then run on Random Forest,
  LightGBM, XGBoost, AdaBoost, and Extra Trees.
- Missing values are imputed for models that need it (constant fill plus a
  missing-indicator flag); XGBoost and LightGBM instead receive raw missing
  values directly, since they handle that natively.

## Key finding so far

Evaluating with a naive random row-split made the model look substantially
better than it actually is — the model was partly memorizing repo-specific
quirks rather than learning something that transfers. Switching to a
genuinely repo-held-out evaluation dropped the apparent performance
noticeably, which is the more honest number. Repeating that evaluation
across several different held-out repo groups gave a consistent read
(~0.69 balanced accuracy, ~0.77 ROC AUC) rather than one that swings
wildly — evidence that the signal is real, if modest, rather than a fluke
of which repos happened to get held out.

## Known limitations

- "Reviewer assigned" is a proxy from review activity, not real assignment
  data — no reviewer-identity data was ever collected.
- No file-path or commit-level data was collected, so features like
  "touches core code" vs. "docs-only" vs. "touches tests" aren't currently
  possible without a new, separate fetch.
- Evaluation currently uses a single repo-grouped train/test split rather
  than a full rotation holding out every repo in turn.
- The author/repo historical features depend on a repo's own accumulated
  history — a repo with no prior data is a genuine cold-start case.
