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
