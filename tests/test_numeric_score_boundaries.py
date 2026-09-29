"""Exercise numeric rejection through the scoring and consistency entrypoints."""
import json

import pytest

from tools.make_fixtures import numeric_score_samples
from tools.sie import evaluate, judge_claude, judges


CASES = numeric_score_samples()['cases']


@pytest.mark.parametrize('name,value,valid', CASES, ids=[row[0] for row in CASES])
def test_score_conversion_boundary_preserves_metadata(name, value, valid, monkeypatch, tmp_path):
    sample = numeric_score_samples()
    artifact = tmp_path / 'artifact.txt'
    artifact.write_text(sample['artifact'], encoding='utf-8')
    response = {
        'available': True,
        'raw': json.dumps({'span_scores': [{'span': sample['span'], 'score': value}]}),
        'provider': 'codexg', 'family': 'codex', 'attempts': sample['attempts'],
    }
    monkeypatch.setattr(judge_claude, 'invoke_claude_judge', lambda *args, **kwargs: response)

    result = judges.score(str(artifact), [{'span': sample['span']}], 'claude')

    assert result['available'] is valid
    assert result['provider'] == 'codexg'
    assert result['family'] == 'codex'
    assert result['attempts'] == sample['attempts']
    assert result['requested_family'] == 'claude'
    if valid:
        assert result['aggregate'] == value
        assert result['span_scores'] == [{'span': sample['span'], 'score': value}]
    else:
        assert result['aggregate'] == 0
        assert result['span_scores'] == []
        assert result['error']


@pytest.mark.parametrize('position', [0, 1])
@pytest.mark.parametrize('name,value,valid', CASES, ids=[row[0] for row in CASES])
def test_consistency_conversion_boundary_is_unavailable(name, value, valid, position):
    pair = [0.5, 0.5]
    pair[position] = value
    result = evaluate.evaluate_c_tier(
        '', [{'task': 'synthetic', 'before': True, 'after': True}], [pair])

    assert result['available'] is valid
    assert result['no_regression'] is valid
    assert result['coverage'] == 0
    assert result['regression_evidence'] == 'available'
    assert result['scenario_eval'] == 'not_implemented'
    if valid:
        assert result['consistency_paired'] == [pair]
        assert result['consistency_evidence'] == 'available'
    else:
        assert result['consistency_paired'] == []
        assert result['consistency_evidence'] == 'missing_or_invalid'
