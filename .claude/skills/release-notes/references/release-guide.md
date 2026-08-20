# Release Notes Guide

## When to write them
After all PRs for a version are merged and you are ready to tag the release.

## Format
```
# 🚀 Release Notes va.b.c

## 🎯 Features
### Big change heading
- change details
- xxxxxx

### Other changes
- drop heading if no big changes
- changelog info

## 🔒 Security & Monitoring
- xxxxxxx

## 📊 Data Model
- xxxxxxx

## ⚡ Integrations
- xxxxxxx

## 🎨 Embeds & UI
- xxxxxxx

## 🤖 GitHub Actions
- xxxxxxx

## 🐛 Bug Fixes & Improvements
- **Bug description:** Rousing action to fix the bug

## 📝 Documentation
- xxxxxxx

## 🔄 Future Enhancements
- xxxxxxx

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/PASTVER…CURRENTVER
```

## Tips
- Drop any section that has nothing to add for the release
- 🎯 Features should highlight the most impactful changes up top
- Bug fixes should be written in plain language — describe what was wrong and what was done
- The changelog link always compares the previous tag to the new one

## Versioning Convention

Versions follow `v<major>.<minor>.<patch>`:
- **Patch** (e.g. v1.7.4 → v1.7.5): Bug fixes, small enhancements, no breaking changes
- **Minor** (e.g. v1.7.x → v1.8.0): New features or meaningful additions
- **Major** (e.g. v1.x.x → v2.0.0): Large rewrites or breaking changes

Always bump `BOT_VERSION` in `features/config.py` to match the release tag before merging.

> ⚠️ **Reminder:** When drafting release notes, always prompt yourself — did you bump `BOT_VERSION` in `features/config.py`? Do not tag the release until this is done.