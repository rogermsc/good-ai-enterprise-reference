# Releasing

This document describes the release process for the Enterprise AI Platform Reference Implementation.

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality in a backward-compatible manner
- **PATCH**: Backward-compatible bug fixes

## Release Process

### 1. Prepare the Release

```bash
# Ensure you're on main and up to date
git checkout main
git pull origin main

# Run full test suite
make test

# Run linting
make lint
```

### 2. Update CHANGELOG.md

Add a new section for the release version:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

### Security
- Security-related changes
```

### 3. Create the Release

```bash
# Commit changelog updates
git add CHANGELOG.md
git commit -m "chore: prepare release vX.Y.Z"

# Create annotated tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"

# Push changes and tag
git push origin main
git push origin vX.Y.Z
```

### 4. Create GitHub Release

1. Go to the repository's Releases page
2. Click "Draft a new release"
3. Select the tag you just created
4. Use the tag name as the release title
5. Copy the relevant CHANGELOG.md section as the description
6. Publish the release

## Pre-release Versions

For pre-release versions, use suffixes:

- `v0.2.0-alpha.1` - Alpha release
- `v0.2.0-beta.1` - Beta release
- `v0.2.0-rc.1` - Release candidate

## Hotfix Process

For urgent fixes to a released version:

```bash
# Create hotfix branch from the release tag
git checkout -b hotfix/vX.Y.Z vX.Y.Z

# Make fixes, commit, and test

# Update version to X.Y.(Z+1)
# Update CHANGELOG.md

# Merge to main (if applicable) and tag
git checkout main
git merge hotfix/vX.Y.Z
git tag -a vX.Y.(Z+1) -m "Hotfix vX.Y.(Z+1)"
git push origin main --tags
```

## Release Checklist

- [ ] All tests passing (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] CHANGELOG.md updated
- [ ] Version tag created
- [ ] GitHub release published
- [ ] Documentation updated (if needed)
