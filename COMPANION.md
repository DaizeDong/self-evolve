# The companion repository contract

This public repository is an **uninitialized tool**. Everything a real run produces lives somewhere
else, in a private repository beside this one, and this file is the contract between the two.

It exists so that a companion built by anyone, on any machine, plugs in without reading this
skill's source. If you are restoring a machine, or wiring up a companion that somebody else made,
this file is the whole interface.

## Why the output lives outside

The 2026-07 audit found real-run output inside public repositories in this fleet: a research
skill's verdict ledger, a shopping skill's purchase records, a social skill's posting account.
Nobody pasted them there. The skills WROTE them there, on every run, by design, because the default
output path was a repository-relative one.

A content scanner cannot catch that. A ticker with an entry price contains no email address and no
phone number, so it looks like nothing to a sieve at the exit. The fix is not a better sieve, it is
that an agent writing this repository has nothing real within reach to copy, because the real thing
is not on this side of the boundary at all.

So every path here belongs to exactly one class, declared in `.dataclass.json`:

| Class | What it is | Where it lives |
|---|---|---|
| TOOL | code, SKILL.md, docs, and metrics ABOUT the skill | here, public, hand written |
| FIXTURE | tests, goldens, examples | here, public, SYNTHETIC and produced by a generator |
| DATA | anything a real run produced | the companion, private, physically absent from here |

## How the companion is found

`tools/datadir.py` probes these locations in order and takes the FIRST ONE THAT EXISTS as a
directory. `<SKILL>` is this repository's name uppercased with hyphens turned into underscores, so
`small-cap-deepdive` becomes `SMALL_CAP_DEEPDIVE`.

| Order | Location | Notes |
|---|---|---|
| 1 | `$<SKILL>_DATA_DIR` | the data directory itself, not a repo root |
| 2 | `$<SKILL>_CONFIG/data`, then `$<SKILL>_CONFIG` | also `$<SKILL>_CONFIG_DIR` |
| 3 | `<sibling>/data`, then `<sibling>` | **the convention**: a directory named `<skill>-config` beside this repository |
| 4 | `~/.<skill>-config/data`, then `~/.<skill>-config` | dotfile in the home directory |
| 5 | `~/.<skill>-data` | last resort |

Two properties of this list are load bearing and were each added after a measured failure.

**The sibling convention is probed at all.** Discovery once depended entirely on an environment
variable, so the answer to "where is this skill's data" depended on whether somebody had remembered
to export something on that particular machine. Measured across eight skills with real data: three
resolved to the companion because their variable happened to be set, three fell through to a home
dotfile while the companion repository sat right beside them, and three answered "uninitialized"
while one of those had 153 tracked files in its companion. Those three were invisible to the
boundary tooling and every report about them was green.

**Both the `data/` subdirectory and the root are probed.** Two shapes exist in this fleet and both
are legitimate. Most companions keep output under `data/`. Some file it directly at the root. A
resolver that knew only one shape reported "no data" for a repository whose files were in plain
sight.

If nothing is found, `resolve_data_dir` returns `None` and the skill must degrade to uninitialized
rather than inventing a path. A resolved directory that turns out to be inside this repository is a
hard error, `DataDirInsideOwnRepo`, never a silent fallback: a fallback into the repository is
precisely the leak this whole boundary exists to prevent.

## The minimum a companion has to be

```
<skill>-config/
  .gitignore        REQUIRED
  README.md         REQUIRED
  data/             where real-run output goes
```

That is the entire requirement. Three things.

- It is a **git repository with a PRIVATE remote**. Private is the point, not un-versioned: the
  companion is exactly where a person's real output legitimately lives, with a history, a diff and
  a backup. The rule is "DATA never in a PUBLIC repo", not "DATA never in git", and conflating the
  two has already produced one wrong verdict in this fleet.
- It sits **beside this repository, not inside it**, and is named `<skill>-config`. Anywhere else
  works only if you also set an environment variable, which is the failure mode above.
- Real output is **tracked or ignored, never loose**. Output that is neither is in a limbo where
  nothing backs it up and where `git status` is buried under so much noise that a genuinely new
  file cannot be seen. Measured on one companion: 35 loose run trees, 1640 files, 1.5 GB, against
  40 tracked files.

Anything else a companion contains is that skill's own business. Several in this fleet carry
`registry.json`, `runbooks/`, `scripts/` or `secrets/`, and those are conventions of one skill
rather than part of this contract. Do not add them to satisfy a checker; nothing checks for them.

## What this repository promises in return

- It **reads** the companion. It does not write this repository's own tree, and no default here
  points inward.
- It **works uninitialized**. With no companion present the skill still loads, still explains
  itself, and reports that it has no data rather than failing.
- It ships **only the schema**. Every declared DATA path has a `<path>.example` beside it here, so
  the shape is public and the content is not.

## Verifying a companion

```
python tools/data_boundary.py                 # this repo holds no run output
python tools/data_boundary.py --explain <name> ...   # would a given output name be recognised
```

`--explain` is the one to reach for when wiring up a companion somebody else built. Feed it the
filenames that companion actually holds. Names it does not recognise are not necessarily wrong, but
they are names this repository's boundary check would not notice if they ever appeared on this side.

`.dataclass.json` carries `_run_shape_probes`, the schematic filenames a real run of this skill
produces. **Schematic is the rule, not a style preference.** A probe carrying a real ticker, a real
mailbox handle, a real account id, a real person or company name is private data in a public
repository even with no file behind it, which would reintroduce the leak under the banner of
preventing it. Write `<ticker>`, `<run-id>`, `<account>`, `<date>` instead.
