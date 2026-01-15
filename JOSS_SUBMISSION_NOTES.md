# JOSS Submission Notes for ObjectState

This document provides guidance for preparing and submitting the ObjectState paper to the Journal of Open Source Software (JOSS).

## Files Created

1. **paper.md** - The main JOSS paper in markdown format
2. **paper.bib** - Bibliography with all references cited in the paper
3. **JOSS_SUBMISSION_NOTES.md** - This file with submission guidance

## Before Submitting

### 1. Update Author Information

**CRITICAL**: Replace the placeholder ORCID in `paper.md`:

```yaml
authors:
  - name: Tristan Simas
    orcid: 0000-0000-0000-0000  # TODO: Replace with actual ORCID
```

- Get your ORCID at [https://orcid.org/](https://orcid.org/)
- Update line 13 of `paper.md` with your actual ORCID number
- If there are co-authors, add them to the authors section

### 2. Verify Repository Requirements

JOSS requires that your repository meets these criteria:

- ✅ **Open source license**: MIT license present in LICENSE file
- ✅ **Version control**: Git repository on GitHub
- ✅ **Documentation**: ReadTheDocs documentation available
- ✅ **Installation instructions**: Present in README.md
- ⚠️ **Tagged release**: Ensure you have a tagged release (e.g., v0.1.0)
- ⚠️ **Community guidelines**: Consider adding CONTRIBUTING.md if not present
- ✅ **Tests**: Comprehensive test suite with 100% coverage
- ⚠️ **Statement of need**: Included in paper.md

### 3. Create a Tagged Release

Before submitting to JOSS, create a release on GitHub:

```bash
git tag -a v0.1.0 -m "Initial JOSS submission"
git push origin v0.1.0
```

Or use GitHub's web interface to create a release.

### 4. Review Paper Content

The paper includes:

- **Summary**: Overview of ObjectState and its novel dual-axis inheritance model
- **Statement of Need**: Explains why this software is needed and who the target audience is
- **State of the Field**: Compares to existing configuration frameworks
- **Implementation & Quality**: Details architecture, components, and quality assurance
- **Example Usage**: Code example demonstrating dual-axis inheritance
- **Research Applications**: Use cases in scientific computing
- **Future Directions**: Planned enhancements

### 5. Check References

All references in `paper.bib` should be accurate and complete. Key reference categories:

- Software engineering best practices (Wilson, Jiménez, Martin, etc.)
- Existing configuration frameworks (Hydra, OmegaConf, pydantic-settings, etc.)
- Python Enhancement Proposals (PEP 557, PEP 567, PEP 484, etc.)
- Design patterns and architecture (Gamma, Fowler, etc.)

### 6. Verify Paper Metadata

Check the YAML frontmatter in `paper.md`:

```yaml
title: Complete and descriptive title ✅
tags: Relevant keywords ✅
authors: Name, ORCID, affiliation ⚠️ (Update ORCID)
affiliations: Institution details ✅
date: Submission date ✅
bibliography: paper.bib ✅
repository-code: GitHub URL ✅
url: Documentation URL ✅
```

## JOSS Submission Process

1. **Pre-submission inquiry** (Optional but recommended):
   - Open an issue at [https://github.com/openjournals/joss-reviews/issues](https://github.com/openjournals/joss-reviews/issues)
   - Use the "Pre-submission inquiry" template
   - Get feedback before formal submission

2. **Formal submission**:
   - Go to [https://joss.theoj.org/papers/new](https://joss.theoj.org/papers/new)
   - Provide repository URL: `https://github.com/trissim/objectstate`
   - The JOSS bot will validate your submission
   - Fix any issues flagged by the bot

3. **Review process**:
   - Editor assigns reviewers
   - Reviewers evaluate software quality, documentation, and paper
   - Address reviewer comments by updating code/docs/paper
   - Typical review takes 4-8 weeks

## JOSS Review Checklist

The reviewers will check:

### Software Quality
- ✅ Installation instructions work
- ✅ Documentation is comprehensive
- ✅ Tests are present and pass
- ✅ Software follows best practices
- ✅ Examples work as documented

### Paper Quality
- ✅ Clear summary of software functionality
- ✅ Statement of need is compelling
- ✅ Comparison to related work
- ✅ References are appropriate
- ✅ Example code works and illustrates key features

### Repository
- ✅ Open source license
- ✅ Community guidelines (CONTRIBUTING.md recommended)
- ✅ Tagged release
- ✅ DOI (will be generated after acceptance)

## Post-Acceptance

After acceptance, JOSS will:

1. Generate a DOI for your software via Zenodo
2. Publish the paper with DOI
3. Create a CrossRef deposit for citations
4. Add your paper to the JOSS website

## Additional Resources

- JOSS Author Guidelines: [https://joss.readthedocs.io/en/latest/submitting.html](https://joss.readthedocs.io/en/latest/submitting.html)
- Example papers: Browse [https://joss.theoj.org/papers/published](https://joss.theoj.org/papers/published)
- Review criteria: [https://joss.readthedocs.io/en/latest/review_criteria.html](https://joss.readthedocs.io/en/latest/review_criteria.html)

## Quick Validation

Before submitting, run these checks:

```bash
# 1. Ensure paper.md and paper.bib are in the repository root
ls paper.md paper.bib

# 2. Validate paper with JOSS preview tool (requires Docker)
docker run --rm -v $(pwd):/data openjournals/paperdraft

# 3. Or use the whedon gem (requires Ruby)
gem install whedon
whedon prepare --paper paper.md

# 4. Check that tests pass
pytest

# 5. Verify documentation builds
cd docs && make html
```

## Contact

For questions about the JOSS submission:
- JOSS discussions: [https://github.com/openjournals/joss/discussions](https://github.com/openjournals/joss/discussions)
- Email: joss@theoj.org

## Version History

- 2026-01-15: Updated with repository metadata and equal-contrib field
- 2026-01-13: Initial JOSS paper draft created
