//! Bake build identity into the exe so the TITLE BAR always shows which build is
//! running. This exists because "修正しました" reports kept landing on machines
//! still running an older deployed exe — with no way for anyone to tell.

use std::process::Command;

fn git(args: &[&str]) -> Option<String> {
    let out = Command::new("git").args(args).output().ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn main() {
    let hash = git(&["rev-parse", "--short", "HEAD"]).unwrap_or_else(|| "nogit".into());
    // uncommitted changes under THIS crate mark the build as local-modified
    let dirty = git(&["status", "--porcelain", "--untracked-files=no", "--", "."])
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let now = chrono::Local::now().format("%m/%d %H:%M").to_string();
    println!(
        "cargo:rustc-env=NATIVE_BUILD_TAG={}{} {}",
        hash,
        if dirty { "+" } else { "" },
        now
    );
    // Re-stamp when the commit moves OR any source changes. Emitting rerun-if-changed
    // narrows cargo's default watching to ONLY these paths — without the src entry the
    // tag froze at the first build's time and lied about freshness.
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=Cargo.toml");
    if let Some(gd) = git(&["rev-parse", "--absolute-git-dir"]) {
        println!("cargo:rerun-if-changed={gd}/HEAD");
    }
}
