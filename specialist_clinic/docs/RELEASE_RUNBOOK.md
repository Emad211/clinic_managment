# A15 release runbook

## Safety model

- The HTTP server is Waitress and binds to `127.0.0.1` by default.
- A random session secret is generated once beside `specialist.db` in
  `.specialist-session-secret`. It is not committed and must be protected with the
  installation folder.
- A fresh database has no default user. Open the application locally and complete
  `/auth/setup`.
- An existing `admin/admin` installation is automatically suspended until that
  password is replaced from the same computer.
- Binding to a non-loopback address is rejected while first-run setup is incomplete.
- The scheduler remains stopped until secure first-run is complete.

## Operator commands

Run from the installation directory:

```powershell
.\SpecialistClinic.exe preflight
.\SpecialistClinic.exe self-test
.\SpecialistClinic.exe backup
.\SpecialistClinic.exe verify-backup "backups\backup_manual_....db"
.\SpecialistClinic.exe restore-backup "backups\backup_manual_....db" `
  --confirm RESTORE-SPECIALIST-DATABASE
```

`restore-backup` verifies the manifest, SHA-256 and SQLite integrity before the
atomic replace. It also creates an independently attested pre-restore backup and
keeps a `specialist.db.before-restore` safety copy.

## Build and acceptance

```powershell
cd specialist_clinic
.\scripts\build_release.ps1
```

The build stops on source self-test, regression, PyInstaller, or frozen self-test
failure. Accepted output:

- `release\SpecialistClinic-win-x64.zip`
- `release\SpecialistClinic-win-x64.zip.sha256`

Before distributing, run `preflight` against a copy of the real deployment folder
and verify that `required_ok` is `true`. `first_run_complete=false` is expected only
before the local setup wizard has been completed.

## Recovery drill

1. Stop every Specialist Clinic process.
2. Copy the full installation folder to offline storage.
3. Run `verify-backup` for the selected backup.
4. Run `restore-backup` with the exact confirmation phrase.
5. Run `preflight`, then `self-test`.
6. Start the app and verify `/health/ready`.

Never point restore at `clinic_new.db`; that accounting database is read-only and is
outside the Specialist Clinic backup/restore boundary.
