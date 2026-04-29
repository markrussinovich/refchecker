from unittest.mock import MagicMock, patch

from refchecker.checkers.github_checker import GitHubChecker


def test_github_owner_url_verifies_as_github_source():
    checker = GitHubChecker()
    reference = {
        'title': 'Qwen-vl 2.5 32b instruct',
        'authors': ['Alibaba DAMO Academy'],
        'venue': 'Qwen2.5-VL',
        'year': 2025,
        'url': 'https://github.com/QwenLM/',
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        'login': 'QwenLM',
        'name': 'QwenLM',
        'company': 'Alibaba Cloud',
        'bio': 'Qwen large language model and multimodal model releases',
        'type': 'Organization',
        'created_at': '2023-01-01T00:00:00Z',
        'public_repos': 20,
    }

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response) as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'GitHub'
    assert verified_data['venue'] == 'GitHub Organization'
    assert errors == []
    assert url == 'https://github.com/QwenLM/'
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == 'https://api.github.com/users/QwenLM'


def test_github_owner_url_404_is_unverified():
    checker = GitHubChecker()
    response = MagicMock()
    response.status_code = 404

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response):
        verified_data, errors, url = checker.verify_reference({'url': 'https://github.com/not-a-real-owner/'})

    assert verified_data is None
    assert errors[0]['error_type'] == 'unverified'
    assert 'owner or organization not found' in errors[0]['error_details'].lower()
    assert url == 'https://github.com/not-a-real-owner/'
