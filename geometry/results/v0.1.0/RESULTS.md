# Geometry verification v0.1.0

This is a post-run analysis of committed observations, not an additional workload campaign.

## Geometric result

The same fixed multiplicative update was applied and closed at three starting compositions drawn from recorded joint epochs 0, 3 and 6. The resulting states are synthetic and have no measured SLO labels.

| Resource | Aitchison distance range | Euclidean share-distance range |
| --- | --- | --- |
| CPU | 0.790041--0.790041 | 0.130375--0.156347 |
| RAM | 0.776836--0.776836 | 0.029149--0.057645 |

Aitchison magnitude and the full ILR displacement vector are invariant for equal relative updates. Common perturbation of both endpoints preserves their Aitchison distance and displacement. The alternate orthonormal CPU basis preserves full-vector distances and turning angles. All checks passed the fixed absolute numerical tolerance of 1e-10.

These verify known properties of the implemented geometry, not newly discovered empirical laws. Euclidean share distance is a valid additive-change measure; it does not have the same invariance under multiplicative changes. Metric scales differ, so the figure compares within-metric variation, not their absolute magnitudes.

Subcomposition dominance is checked separately. Removing components can change Aitchison distance; this analysis does not claim that all reduced distances or angles remain equal.

## Recorded runtime observations

| Separate series | Policy | Histories | Histories with valid unsafe epochs |
| --- | --- | --- |
| migration | control | 19 | 0 |
| migration | drift | 19 | 19 |
| joint | control | 20 | 0 |
| joint | cpu | 20 | 14 |
| joint | joint | 20 | 20 |
| joint | ram | 20 | 17 |

The joint series retains 5 blocks with a matched joint-only unsafe witness. No later stopped epochs are imputed. Every CSV observation, including its validity flags and original SLO outcome, is retained; series are not pooled. The CPU migration source contains 19 of its 20 planned blocks; the missing source block supplies no observations and is not reconstructed.

The migration records show pressure-motivated, closed CPU transfers with measured recipient output and externally observed checkout outcomes. The CPU/RAM records show that jointly changing two resource compositions can cross the SLO at a step where each single-resource history remains safe. These support operational relevance of allocation direction and joint context, not universal predictive superiority of a metric.

## Representation and interpretation

CPU uses all three orthonormal coordinates: functional services versus advertising, checkout versus payment/shipping, and payment versus shipping. RAM uses checkout versus advertising. Signed drift is an ILR-coordinate difference from the respective resource reference. CPU and RAM bytes are never closed together.

The CPU/RAM state has four coordinates. The displayed projection uses only two; full distances use all four. The product distance uses CPU=1 and RAM=1 as explicit weights. These are a descriptive convention, not uniquely implied by CoDA, physical unit conversion, statistical independence, or calibrated risk weights. No topology of a safe region is inferred.

A geometrically appropriate relative-drift metric is not automatically a distance to an SLO boundary. Actual capacity and workload remain relevant. No threshold fitting, accuracy comparison, production prevalence, or transport of SLO labels to synthetic states is performed.

## Files and provenance

- [Full observed coordinates](trajectory-coordinates.csv)
- [Synthetic property checks](metric-properties.csv)
- [Machine-readable verification and source hashes](summary.json)
- [Geometry and observed-outcome figure](geometry.svg)

Analysis execution: run `38128412179`, commit `290d9701483b7368f3b65c2ef94d27d6e326d07a`. Input hashes use LF text as stored in Git. Runtime execution provenance remains in the unchanged source series.
