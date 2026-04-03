# Installer validation, transactions, failure analysis, release gate

This document ties together **test strategy**, **transactional patterns**, **failure simulations**, **residual mitigations**, and a **release go/no-go**. It complements `install_ragnar.sh` and `Ragnar/scripts/boot_validate.inc`.

---

## 1. Test and validation strategy

### Automated (run before every release)

| Step | Command | Expected |
|------|---------|----------|
| Syntax | `bash -n install_ragnar.sh` | Exit 0 |
| Embedded sync | `Ragnar/scripts/installer_diff_embedded_boot_validate.sh` | `OK: embedded ... matches` |
| Harness | `Ragnar/scripts/installer_test_harness.sh` | `HARNESS PASS` |
| Live boot (on Pi, root) | `sudo Ragnar/scripts/validate_boot_files.sh` | Exit 0 |

```bash
cd /path/to/repo
chmod +x Ragnar/scripts/installer_test_harness.sh Ragnar/scripts/installer_diff_embedded_boot_validate.sh
./Ragnar/scripts/installer_test_harness.sh ./install_ragnar.sh
```

CI: add a job that runs `installer_diff_embedded_boot_validate.sh` and `installer_test_harness.sh` on every push touching `install_ragnar.sh` or `boot_validate.inc`.

### Manual test matrix

#### Fresh install

1. Flash current Raspberry Pi OS Lite (64-bit or 32-bit per your support matrix).
2. Boot, enable SSH, copy **full repo** or `wget` installer per README.
3. Run `sudo ./install_ragnar.sh`, complete prompts.
4. **Expected:** Installer finishes; `sudo Ragnar/scripts/validate_boot_files.sh`; `sudo systemctl is-active ragnar`; reboot; services still active; `journalctl -b -u ragnar` clean enough for your bar.

#### Re-run (idempotency)

1. After successful install, run `sudo ./install_ragnar.sh` again (same choices).
2. **Expected:** No duplicate `modules-load=dwc2,g_ether`; `validate_boot_files.sh` passes; `gpu_mem` single line per file; app tree replaced (unless `RAGNAR_INSTALLER_BACKUP_APP=1`).

**Limitation:** First-run `.ragnar.bak` is **not** refreshed — second run still restores **stale** backup on FATAL validation. Mitigation: `RAGNAR_BOOT_BACKUP_VERSIONED=1` for timestamped copies.

#### Power loss simulation (safe-ish)

**Do not yank power on your only production SD without a backup image.**

| Injection point | Safe simulation | Expected |
|-----------------|-----------------|----------|
| After boot edits | Pause script after `ragnar_validate_boot_after_install` (temporary `read -p`), sync, snapshot SD in VM, or use `losetup` + ext4/vfat image | If torn write: fsck may fix; worst case re-flash |
| During `apt` | Snapshot before `apt`; kill -9 installer mid-apt | `dpkg --configure -a` may recover; not installer’s job to fix |

**Practical approach:** Use a **spare SD** or **qemu** with mounted `/boot` loop image; run installer in `script(1)` session; kill at chosen line. Document outcome (bootable / not).

#### Missing or corrupted boot files

1. **Missing `config.txt`:** `ragnar_installer_require_boot_files` exits immediately — **expected:** FATAL, no fake file created.
2. **Corrupted cmdline (multi-line):** `ragnar_validate_boot_after_install` fails → restore `.ragnar.bak` → **expected:** installer aborts; user must fix duplicate lines manually if backup was also bad.

#### Low memory (512MB Pi Zero 2 W)

1. Run full install on hardware or `systemd-run` with memory limit if you must simulate.
2. **Expected:** `gpu_mem` ≤ 128 for 512MB after clamp; `TROUBLESHOOTING.md` thresholds; optional `RAGNAR_INSTALLER_LOG=/tmp/x.log` if `/var/log` tight.

---

## 2. Lightweight transactional model (bash-only)

Full transactional install (apt + pip + git) **cannot** be atomic without snapshots or images. What **can** be staged:

### Boot config (pattern you already use)

1. **`ragnar_boot_backup`** → `.ragnar.bak` (+ optional `RAGNAR_BOOT_BACKUP_VERSIONED=1` timestamped files).
2. **Edit** → `config.txt` / `cmdline.txt` (or temp write + `mv`).
3. **`ragnar_validate_boot_after_install`** → on failure **`ragnar_boot_restore_from_bak`**.
4. **`sync`** → flush VFAT.

**gpu_mem sub-transaction:** `.ragnar.gpu-snap` per step; restore on validation failure (already implemented).

### Stronger staging (optional upgrade)

```bash
# Pseudocode — not in tree by default
stage="/run/ragnar-install/boot-stage"
mkdir -p "$stage"
cp -a /boot/firmware/config.txt "$stage/config.txt"
# edit "$stage/config.txt"
if ragnar_validate_config_txt "$stage/config.txt"; then
  cp -a "$stage/config.txt" /boot/firmware/config.txt
  sync
else
  echo "reject staged config"
fi
```

Use `/run` (tmpfs) for staging copies — **low RAM**, no extra disk dependency.

### Commit point

Treat **`ragnar_validate_boot_after_install` success + `sync`** as the **commit** for boot files. Everything before that is **rollbackable** via `.ragnar.bak` / gpu snap.

---

## 3. Failure scenarios (current design)

### 1) Power loss immediately after modifying `config.txt`

- **What happens:** VFAT may leave a **torn** file (truncate or half-write).
- **Boot:** May still boot if kernel params intact; may hang or kernel panic if `config.txt` unreadable.
- **Recovery:** fsck on next mount; restore from `.ragnar.bak` on another machine; re-image.
- **Residual risk:** **No installer can guarantee** VFAT atomicity without redundant copies on medium.

**Mitigation already:** `sync` after validation; optional **versioned backups** (`RAGNAR_BOOT_BACKUP_VERSIONED=1`).

### 2) Power loss during `apt install`

- **What happens:** dpkg incomplete; system may boot with broken packages.
- **Installer:** Does not wrap `apt` in a transaction.
- **Recovery:** `sudo dpkg --configure -a`, `sudo apt -f install`.

### 3) Crash before `gpu_mem` validation

- **What happens:** If crash **after** write but **before** validation, `.ragnar.gpu-snap` might still exist on disk; next run overwrites flow. If crash **during** write, gpu snap may restore inconsistent state — rare.
- **Boot:** Usually still boots; `gpu_mem` might be wrong until next successful run.

### 4) Re-run after partial install

- **What happens:** Boot may be valid; `~/Ragnar` may be missing or half-copied (`rm -rf` then failed `cp`).
- **Recovery:** Re-run installer; optional `RAGNAR_INSTALLER_BACKUP_APP=1` before wipe.

### 5) Corrupted or manually edited `config.txt`

- **Validation:** `ragnar_validate_config_txt` only checks “some active line” — **does not** validate every `dtoverlay=` pairing.
- **If user breaks file:** FATAL at end of boot section if cmdline still valid but config empty — restore `.ragnar.bak`.

**Targeted improvement:** optional Raspberry Pi–specific semantic checks remain out of scope for a minimal script.

---

## 4. Weak points and concrete mitigations

| Weak point | Mitigation (implemented or proposed) |
|------------|-------------------------------------|
| Heredoc drift | **`installer_diff_embedded_boot_validate.sh`** — CI gate |
| Single `.ragnar.bak` | **`RAGNAR_BOOT_BACKUP_VERSIONED=1`** — `*.ragnar.<UTC>.bak` copies each run |
| VFAT corruption | **`sync`** after boot commit; avoid unnecessary `config.txt` rewrites |
| No full transaction | Document **commit boundary** = validate + sync; stage under `/run` if you add more editors |

### Bash: versioned backup (env)

```bash
sudo RAGNAR_BOOT_BACKUP_VERSIONED=1 ./install_ragnar.sh
```

### Bash: runtime drift check before install

```bash
./Ragnar/scripts/installer_diff_embedded_boot_validate.sh || exit 1
```

---

## 5. Release gate (strict)

### Go / no-go

- **NO-GO** by default until:
  - `installer_diff_embedded_boot_validate.sh` passes on the release commit.
  - `installer_test_harness.sh` passes.
  - At least one **full fresh install** on real hardware (512MB + 1GB+) on the target OS image.
- **GO** only if the checklist below is satisfied and known issues are documented for users.

### Remaining high-risk areas

1. **VFAT / power loss** — mitigated, not eliminated.
2. **`apt` / `pip` partial state** — operator recovery (`dpkg --configure -a`, pip reinstall).
3. **Embedded vs file drift** — eliminated only if CI runs the diff script.
4. **Idempotent semantics** — re-run **replaces** app tree; data loss if no backup.

### Pre-release checklist

- [ ] `installer_diff_embedded_boot_validate.sh` → OK  
- [ ] `installer_test_harness.sh` → HARNESS PASS  
- [ ] `bash -n install_ragnar.sh`  
- [ ] Fresh install test on hardware  
- [ ] Re-run install test  
- [ ] `sudo validate_boot_files.sh` on installed system  
- [ ] `gpu_mem` sane on 512MB board (`grep gpu_mem /boot/firmware/config.txt`)  
- [ ] Document wget-only path: embedded block must match (CI enforces)  
- [ ] `RAGNAR_INSTALLER_LOG` readable and not filling disk on long runs  

### Last critical fixes before tag

- None required beyond **sync + validation + diff script** if those pass — **block release** if diff fails.

---

## Scripts reference

| Script | Purpose |
|--------|---------|
| `Ragnar/scripts/installer_test_harness.sh` | Syntax, embedded diff, mock validation, gpu sanity, optional live `validate_boot_files` |
| `Ragnar/scripts/installer_diff_embedded_boot_validate.sh` | Fail if heredoc ≠ `boot_validate.inc` |
| `Ragnar/scripts/validate_boot_files.sh` | Live `/boot/firmware` check (root) |
