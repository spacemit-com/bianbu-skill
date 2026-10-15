#!/usr/bin/env python3
"""Fail closed when result coverage, calculations, history or evidence is incomplete."""
import argparse
import json
import math
from pathlib import Path
import statistics


def audit(out):
    manifest = json.loads((out / 'manifest.json').read_text())
    results = json.loads((out / 'results.json').read_text())
    errors = []
    manifest_ids, result_ids = {row['id'] for row in manifest}, {row['id'] for row in results}
    if len(manifest_ids) != len(manifest): errors.append('manifest IDs are not unique')
    if len(result_ids) != len(results): errors.append('result IDs are not unique')
    if manifest_ids != result_ids: errors.append(f'coverage mismatch missing={sorted(manifest_ids-result_ids)} extra={sorted(result_ids-manifest_ids)}')
    configurations = 0
    for row in results:
        if row.get('recipe', {}).get('kind') == 'audio':
            if row.get('status') != 'skipped_policy':
                errors.append(f'{row["id"]}: audio model was not filtered by policy')
            if row.get('artifact') or row.get('measurements'):
                errors.append(f'{row["id"]}: filtered audio model has artifact or measurements')
        if not row.get('attempts'): errors.append(f'{row["id"]}: missing attempts history')
        if row.get('status') in {'within_threshold', 'confirmed_regression', 'review_required', 'environment_mismatch', 'baseline_mismatch'}:
            if not row.get('measurements'): errors.append(f'{row["id"]}: terminal measured status without measurements')
            if not row.get('selected_run_id') or not row.get('selection_reason'): errors.append(f'{row["id"]}: missing selection provenance')
        for metric in row.get('measurements', []):
            configurations += 1
            samples = metric.get('samples', [])
            if len(samples) < 3: errors.append(f'{row["id"]}/{metric.get("metric")}: fewer than 3 measured samples')
            elif not math.isclose(statistics.median(samples), metric.get('actual', math.nan), rel_tol=1e-12, abs_tol=1e-12):
                errors.append(f'{row["id"]}/{metric.get("metric")}: median mismatch')
            baseline, actual = metric.get('baseline'), metric.get('actual')
            if baseline and actual:
                delta = (actual - baseline) / baseline * 100
                if not math.isclose(delta, metric.get('delta_pct', math.nan), rel_tol=1e-10, abs_tol=1e-10):
                    errors.append(f'{row["id"]}/{metric.get("metric")}: delta mismatch')
            log_dir = Path(metric.get('log_dir', ''))
            if not log_dir.exists(): errors.append(f'{row["id"]}/{metric.get("metric")}: missing log directory {log_dir}')
            if metric.get('performance_status') == 'confirmed_regression':
                initial = metric.get('initial')
                if not initial or initial.get('performance_status') != 'regression_candidate':
                    errors.append(f'{row["id"]}/{metric.get("metric")}: confirmed regression lacks initial candidate')
        if row.get('status') == 'skipped_size' and (row.get('bytes') or 0) <= row.get('size_limit_bytes', 5_000_000_000):
            errors.append(f'{row["id"]}: skipped_size does not exceed default threshold')
    report = {'models_manifest': len(manifest), 'models_results': len(results),
        'configurations': configurations, 'errors': errors, 'result': 'FAIL' if errors else 'PASS'}
    (out / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    raise SystemExit(audit(parser.parse_args().out.resolve()))
