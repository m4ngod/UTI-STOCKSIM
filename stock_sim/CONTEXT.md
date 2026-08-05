# Strategy Diagnostics Laboratory

This context describes the reproducible scenario experiments used to diagnose
how a Strategy Under Test responds to controlled A-share market conditions.

## Language

**Campaign Case**:
An immutable, content-identified scenario condition and its declared comparison relationship inside a Diagnostic Campaign.
_Avoid_: Test case, run configuration

**Baseline Scenario Set**:
The control layer whose cases use an approved Historical Market Segment without market-path transformations.
_Avoid_: Default scenario, normal case

**Isolated Sensitivity Set**:
The attribution layer whose cases vary exactly one Scenario Transformation family at a time while comparable inputs and controlled random sources remain fixed.
_Avoid_: Parameter test, mixed sweep

**Sensitivity Sweep Definition**:
An immutable, bounded set of explicitly approved and materialized levels for one registered Scenario Transformation family; expanding it produces Campaign Cases without granting new recipe approval authority.
_Avoid_: Automatic optimization, unapproved parameter search

**Compound Scenario Set**:
The stress layer whose cases intentionally combine multiple declared Scenario Transformation families.
_Avoid_: Isolated sweep, baseline

**Formal Diagnostic Campaign**:
A complete diagnostic comparison containing Baseline, Isolated Sensitivity, and Compound Scenario Sets with declared comparison relationships.
_Avoid_: Backtest, quick experiment

**Quick Experiment**:
An incomplete or selectively composed scenario comparison that does not claim formal diagnostic attribution.
_Avoid_: Formal Diagnostic Campaign

**Scenario Execution Resolution**:
An immutable backend resolution of requested and effective execution conditions for exact Strategy Under Test and Campaign Case targets, including the first market node strictly after Decision Time and typed override reasons.
_Avoid_: Frontend estimate, editable execution policy

**Scenario Selection Context**:
The immutable, content-identified formal handoff candidate binding the exact Strategy Under Test set, Scenario Set, Campaign Cases, Approved Scenario Recipe versions and hashes, Reference Market Paths, execution resolution, source generation, and originating selection/view revisions.
_Avoid_: QML payload, copied campaign configuration

**Diagnostic Setup Selection Context**:
An immutable typed navigation intent that combines one current formal Strategy Selection Context with one current formal Scenario Selection Context and converts those exact identities into the existing Diagnostic Task Configuration; it never owns or copies upstream truth.
_Avoid_: Generic setup dictionary, frontend campaign builder

**Diagnostic Selection Dependency Binding**:
The immutable backend validation and approval dependency record for the exact Strategy and Scenario setup source, content hash, and Diagnostic Task revision. An AppContext-owned typed coordinator presents the current setup to existing Diagnostic Tasks operations; authoritative backend reread and later commands invalidate active validation and approval after upstream drift while retaining their history.
_Avoid_: Editable approval input, cached QML state
