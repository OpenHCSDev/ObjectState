# Badge and Documentation Setup

This document explains the badges added to the README and the manual setup steps required.

## Badges Added

### 1. Read the Docs Badge
```markdown
[![Documentation Status](https://readthedocs.org/projects/objectstate/badge/?version=latest)](https://objectstate.readthedocs.io/en/latest/?badge=latest)
```
- **Status**: Should work automatically if objectstate is registered on ReadTheDocs
- **Link**: https://objectstate.readthedocs.io
- **Configuration**: `.readthedocs.yaml` is already configured

### 2. Code Coverage Badge
```markdown
[![Coverage](https://raw.githubusercontent.com/trissim/objectstate/main/.github/badges/coverage.svg)](https://trissim.github.io/objectstate/coverage/)
```
- **Status**: Will be automatically updated by GitHub Actions workflow
- **Link**: https://trissim.github.io/objectstate/coverage/
- **Workflow**: `.github/workflows/coverage-pages.yml`

## Manual Setup Required

### 1. Enable GitHub Pages
The coverage badge and reports require GitHub Pages to be enabled:

1. Go to: https://github.com/trissim/objectstate/settings/pages
2. Under "Build and deployment":
   - **Source**: Select "GitHub Actions"
3. Save the settings

Once enabled, the coverage reports will be available at:
- Badge SVG: https://raw.githubusercontent.com/trissim/objectstate/main/.github/badges/coverage.svg
- Coverage Report: https://trissim.github.io/objectstate/coverage/

### 2. Update Repository Description (Optional but Recommended)
To match the problem statement requirement:

1. Go to: https://github.com/trissim/objectstate
2. Click the ⚙️ (settings) icon next to "About"
3. Add or update:
   - **Description**: Generic lazy dataclass configuration framework with dual-axis inheritance
   - **Website**: https://objectstate.readthedocs.io
   - **Topics**: Add relevant tags like `python`, `configuration`, `dataclass`, etc.
4. Save changes

### 3. Verify ReadTheDocs Integration
Ensure the repository is properly linked to ReadTheDocs:

1. Go to: https://readthedocs.org/dashboard/
2. Verify `objectstate` project exists
3. Check webhook is configured at: https://github.com/trissim/objectstate/settings/hooks
4. Trigger a build to ensure documentation is up to date

## How the Coverage Badge Works

The coverage badge is similar to the ezstitcher repository setup:

1. On every push to `main` branch, the `coverage-pages.yml` workflow:
   - Runs tests with coverage
   - Generates a coverage badge SVG at `.github/badges/coverage.svg`
   - Commits the badge back to the repository
   - Deploys HTML coverage reports to GitHub Pages

2. The badge in README.md links to:
   - SVG file from the `main` branch (always up-to-date)
   - Coverage report hosted on GitHub Pages

## Testing the Setup

After enabling GitHub Pages:

1. Push a commit to the `main` branch
2. Wait for the "Tests, Coverage and GitHub Pages" workflow to complete
3. Check that:
   - The badge SVG was updated in `.github/badges/coverage.svg`
   - The coverage report is available at https://trissim.github.io/objectstate/coverage/
   - The badge in README shows the correct coverage percentage

## Differences from Codecov

This setup uses GitHub Pages for coverage reports instead of Codecov.io:

**Advantages:**
- No external service account required
- No API tokens needed
- Works out of the box
- Reports hosted on your GitHub Pages

**CI Workflow:**
- The existing `ci.yml` workflow still uploads to Codecov if configured
- The new `coverage-pages.yml` workflow generates the badge and GitHub Pages
- Both can coexist - Codecov for CI checks, GitHub Pages for the badge
