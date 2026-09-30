#!/usr/bin/env python3
"""
Tiny Codex 3-gate orchestrator.

Design goals:
- no third-party Python packages
- state is visible in feature.json
- Codex writes documentation through structured final output; this script persists it
- humans are interrupted only at Gate 1, Gate 2, and Gate 3
- implementation/review/fix loops happen automatically

Requires:
- Python 3.10+
- Codex CLI installed and authenticated
"""

from __future__ import annotations
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "schemas" / "agent_response.schema.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def feature_dir(feature_file: Path) -> Path:
    return feature_file.resolve().parent


def resolve(feature_file: Path, value: str) -> Path:
    return (feature_dir(feature_file) / value).resolve()


def artifact(feature_file: Path, name: str) -> Path:
    p = feature_dir(feature_file) / "artifacts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def gate_file(feature_file: Path, gate: int) -> Path:
    p = feature_dir(feature_file) / "gates" / f"gate{gate}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def answer_file(feature_file: Path, gate: int) -> Path:
    return feature_dir(feature_file) / "gates" / f"gate{gate}_answers.md"


def log_file(feature_file: Path, stage: str) -> Path:
    p = feature_dir(feature_file) / "logs" / f"{stage}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def prompt(name: str, **values: str) -> str:
    text = (ROOT / "prompts" / name).read_text(encoding="utf-8")
    return text.format(**values)


def repo_entries(feature_file: Path, cfg: dict[str, Any]) -> list[tuple[str, Path, str]]:
    out = []
    for repo in cfg.get("repositories", []):
        out.append(
            (repo["name"], resolve(feature_file, repo["path"]), repo.get("verify", ""))
        )
    return out


def repo_rules_text(feature_file: Path, cfg: dict[str, Any]) -> str:
    lines = []
    for name, path, _ in repo_entries(feature_file, cfg):
        lines.append(f"- {name}: {path / 'AGENTS.md'}")
    return "\n".join(lines)


def run_codex(
    feature_file: Path,
    cfg: dict[str, Any],
    stage: str,
    prompt_text: str,
    *,
    write: bool = False,
) -> dict[str, Any]:
    workspace = resolve(feature_file, cfg.get("workspace_root", "."))
    output = log_file(feature_file, stage)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--cd", str(workspace),
        "--output-schema", str(SCHEMA),
        "--output-last-message", str(output),
        "--sandbox", "workspace-write" if write else "read-only",
    ]

    # Permit implementation in all declared repos while keeping one workspace.
    if write:
        for _, repo_path, _ in repo_entries(feature_file, cfg):
            cmd += ["--add-dir", str(repo_path)]

    print(f"\n=== {stage} ===")
    print("Running:", " ".join(shlex.quote(x) for x in cmd[:-1]), "<prompt>")

    completed = subprocess.run(
        cmd + [prompt_text],
        text=True,
        cwd=workspace,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Codex failed in stage {stage} with exit code {completed.returncode}")
    if not output.exists():
        raise RuntimeError(
            f"Codex exited without creating {output}. "
            "Check Codex CLI stderr/output and your CLI version."
        )

    try:
        result = load_json(output)
    except Exception as exc:
        raise RuntimeError(f"Invalid structured output in {output}: {exc}") from exc
    return result


def write_gate(feature_file: Path, gate: int, title: str, result: dict[str, Any]) -> None:
    lines = [f"# Gate {gate} — {title}", "", result.get("summary", ""), ""]
    decisions = result.get("decisions", [])
    if decisions:
        lines += ["## Decisions", ""]
        for d in decisions:
            lines += [
                f"### {d['id']}",
                "",
                d["question"],
                "",
                "**Options:**",
            ]
            lines += [f"- {x}" for x in d["options"]]
            lines += [
                "",
                f"**AI recommendation:** {d['recommendation']}",
                "",
                f"**Reason:** {d['reason']}",
                "",
                "**Your answer:**",
                "",
                "<write decision here>",
                "",
            ]
    gate_file(feature_file, gate).write_text("\n".join(lines), encoding="utf-8")


def require_answers(feature_file: Path, gate: int) -> str:
    p = answer_file(feature_file, gate)
    if not p.exists():
        raise RuntimeError(
            f"Gate {gate} is waiting for you.\n"
            f"Read:   {gate_file(feature_file, gate)}\n"
            f"Create: {p}\n"
            f"Then run the orchestrator again."
        )
    return p.read_text(encoding="utf-8")


def save_artifact(path: Path, result: dict[str, Any]) -> None:
    content = result.get("content", "").strip()
    if not content:
        raise RuntimeError(f"Agent returned no artifact content for {path.name}")
    path.write_text(content + "\n", encoding="utf-8")


def verification_commands(feature_file: Path, cfg: dict[str, Any]) -> str:
    reports = []
    for name, path, command in repo_entries(feature_file, cfg):
        if not command:
            reports.append(f"{name}: SKIPPED (no verify command configured)")
            continue
        print(f"\n--- verify {name}: {command}")
        p = subprocess.run(
            command,
            shell=True,
            cwd=path,
            text=True,
            capture_output=True,
        )
        reports.append(
            f"## {name}\n"
            f"command: {command}\n"
            f"exit_code: {p.returncode}\n"
            f"stdout:\n{p.stdout[-6000:]}\n"
            f"stderr:\n{p.stderr[-6000:]}"
        )
    return "\n\n".join(reports)


def run(feature_file: Path) -> None:
    cfg = load_json(feature_file)
    state = cfg.get("state", "NEW")
    context = resolve(feature_file, cfg["product_context"])
    spec = artifact(feature_file, "spec.md")
    design = artifact(feature_file, "design.md")
    tasks = artifact(feature_file, "tasks.md")
    rules = repo_rules_text(feature_file, cfg)

    # -------- Gate 1: product --------
    if state == "NEW":
        r = run_codex(
            feature_file, cfg, "01_specify",
            prompt(
                "specify.md",
                feature_title=cfg["title"],
                product_context=str(context),
            ),
        )
        save_artifact(spec, r)

        review = run_codex(
            feature_file, cfg, "02_review_spec",
            prompt(
                "review_spec.md",
                spec_path=str(spec),
                product_context=str(context),
            ),
        )

        if review.get("decisions"):
            write_gate(feature_file, 1, "Product decisions", review)
            cfg["state"] = "GATE_1"
            save_json(feature_file, cfg)
            print(f"\nSTOP: Gate 1 needs human input: {gate_file(feature_file, 1)}")
            return

        repaired = run_codex(
            feature_file, cfg, "03_repair_spec",
            prompt(
                "repair_spec.md",
                spec_path=str(spec),
                review_content=json.dumps(review, indent=2),
                human_decisions="None.",
            ),
        )
        save_artifact(spec, repaired)
        cfg["state"] = "SPEC_APPROVED"
        save_json(feature_file, cfg)
        state = cfg["state"]

    if state == "GATE_1":
        answers = require_answers(feature_file, 1)
        review = load_json(log_file(feature_file, "02_review_spec"))
        repaired = run_codex(
            feature_file, cfg, "03_repair_spec",
            prompt(
                "repair_spec.md",
                spec_path=str(spec),
                review_content=json.dumps(review, indent=2),
                human_decisions=answers,
            ),
        )
        save_artifact(spec, repaired)
        cfg["state"] = "SPEC_APPROVED"
        save_json(feature_file, cfg)
        state = cfg["state"]

    # -------- Gate 2: architecture/risk --------
    if state == "SPEC_APPROVED":
        d = run_codex(
            feature_file, cfg, "04_design",
            prompt(
                "design.md",
                spec_path=str(spec),
                repo_rules=rules,
            ),
        )
        save_artifact(design, d)

        review = run_codex(
            feature_file, cfg, "05_review_design",
            prompt(
                "review_design.md",
                spec_path=str(spec),
                design_path=str(design),
                repo_rules=rules,
            ),
        )

        decisions = list(d.get("decisions", [])) + list(review.get("decisions", []))
        if decisions:
            combined = dict(review)
            combined["decisions"] = decisions
            write_gate(feature_file, 2, "Architecture / risk decisions", combined)
            cfg["state"] = "GATE_2"
            save_json(feature_file, cfg)
            print(f"\nSTOP: Gate 2 needs human input: {gate_file(feature_file, 2)}")
            return

        repaired = run_codex(
            feature_file, cfg, "06_repair_design",
            prompt(
                "repair_design.md",
                spec_path=str(spec),
                design_path=str(design),
                review_content=json.dumps(review, indent=2),
                human_decisions="None.",
            ),
        )
        save_artifact(design, repaired)

        t = run_codex(
            feature_file, cfg, "07_tasks",
            prompt(
                "tasks.md",
                spec_path=str(spec),
                design_path=str(design),
            ),
        )
        save_artifact(tasks, t)
        cfg["state"] = "READY_TO_IMPLEMENT"
        save_json(feature_file, cfg)
        state = cfg["state"]

    if state == "GATE_2":
        answers = require_answers(feature_file, 2)
        review = load_json(log_file(feature_file, "05_review_design"))
        repaired = run_codex(
            feature_file, cfg, "06_repair_design",
            prompt(
                "repair_design.md",
                spec_path=str(spec),
                design_path=str(design),
                review_content=json.dumps(review, indent=2),
                human_decisions=answers,
            ),
        )
        save_artifact(design, repaired)
        t = run_codex(
            feature_file, cfg, "07_tasks",
            prompt(
                "tasks.md",
                spec_path=str(spec),
                design_path=str(design),
            ),
        )
        save_artifact(tasks, t)
        cfg["state"] = "READY_TO_IMPLEMENT"
        save_json(feature_file, cfg)
        state = cfg["state"]

    # -------- Autonomous implementation / review / repair --------
    if state == "READY_TO_IMPLEMENT":
        impl = run_codex(
            feature_file, cfg, "08_implement",
            prompt(
                "implement.md",
                spec_path=str(spec),
                design_path=str(design),
                tasks_path=str(tasks),
                repo_rules=rules,
            ),
            write=True,
        )
        if impl.get("status") == "needs_human":
            write_gate(feature_file, 2, "Implementation discovered architecture conflict", impl)
            cfg["state"] = "GATE_2"
            save_json(feature_file, cfg)
            print(f"\nSTOP: implementation escalated to Gate 2: {gate_file(feature_file, 2)}")
            return

        cfg["state"] = "VERIFYING"
        save_json(feature_file, cfg)
        state = cfg["state"]

    if state == "VERIFYING":
        max_fixes = int(cfg.get("max_fix_iterations", 2))
        final_review = None

        for attempt in range(max_fixes + 1):
            checks = verification_commands(feature_file, cfg)
            review = run_codex(
                feature_file, cfg, f"09_verify_{attempt}",
                prompt(
                    "verify.md",
                    spec_path=str(spec),
                    design_path=str(design),
                    tasks_path=str(tasks),
                    verify_results=checks,
                ),
            )
            final_review = review

            if review.get("decisions"):
                write_gate(feature_file, 2, "Verification discovered decision", review)
                cfg["state"] = "GATE_2"
                save_json(feature_file, cfg)
                print(f"\nSTOP: verification escalated to Gate 2: {gate_file(feature_file, 2)}")
                return

            serious = [
                f for f in review.get("findings", [])
                if f.get("severity") in ("blocker", "major")
            ]
            if not serious:
                break

            if attempt >= max_fixes:
                break

            fix = run_codex(
                feature_file, cfg, f"10_fix_{attempt}",
                prompt(
                    "fix.md",
                    spec_path=str(spec),
                    design_path=str(design),
                    tasks_path=str(tasks),
                    review_content=json.dumps(review, indent=2),
                ),
                write=True,
            )
            if fix.get("status") == "needs_human":
                write_gate(feature_file, 2, "Fix requires architecture decision", fix)
                cfg["state"] = "GATE_2"
                save_json(feature_file, cfg)
                print(f"\nSTOP: fix escalated to Gate 2: {gate_file(feature_file, 2)}")
                return

        # Gate 3 is intentionally always human, but the human receives only a compact outcome.
        write_gate(
            feature_file,
            3,
            "Outcome / release",
            {
                "summary": (
                    "Implementation and automated AI review are complete. "
                    "Inspect the actual application behavior and decide whether to merge/release."
                ),
                "decisions": [{
                    "id": "RELEASE",
                    "question": "Is the implemented feature acceptable to merge/release?",
                    "options": ["APPROVE", "REJECT / describe issue"],
                    "recommendation": "APPROVE only after checking the user-visible outcome.",
                    "reason": "Gate 3 is the human product-outcome check."
                }],
                "findings": (final_review or {}).get("findings", []),
            },
        )
        cfg["state"] = "GATE_3"
        save_json(feature_file, cfg)
        print(f"\nSTOP: Gate 3 ready: {gate_file(feature_file, 3)}")
        return

    if state == "GATE_3":
        answers = require_answers(feature_file, 3)
        normalized = answers.upper()
        if "APPROVE" in normalized and "REJECT" not in normalized:
            cfg["state"] = "DONE"
            save_json(feature_file, cfg)
            print("\nDONE: feature approved.")
        else:
            print(
                "\nGate 3 was not approved. "
                "Edit feature.json state to READY_TO_IMPLEMENT after updating the approved artifacts, "
                "or handle the requested product change explicitly."
            )
        return

    if state == "DONE":
        print("Feature is already DONE.")


def reset(feature_file: Path) -> None:
    cfg = load_json(feature_file)
    cfg["state"] = "NEW"
    save_json(feature_file, cfg)
    for folder in ("artifacts", "logs", "gates"):
        p = feature_dir(feature_file) / folder
        if p.exists():
            for child in p.iterdir():
                if child.is_file():
                    child.unlink()
    print("Reset complete.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "feature",
        nargs="?",
        default=str(ROOT / "features" / "F001-example" / "feature.json"),
        help="Path to feature.json",
    )
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    ff = Path(args.feature).resolve()
    if args.reset:
        reset(ff)
    else:
        run(ff)


if __name__ == "__main__":
    main()
