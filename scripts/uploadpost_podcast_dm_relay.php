<?php
declare(strict_types=1);

/*
 * Upload-Post Podcast-Link DM Relay
 *
 * Deploy this file to your PHP webspace and run this command every 2 minutes:
 *   /usr/bin/php /path/uploadpost_podcast_dm_relay.php cron YOUR_RELAY_PASSWORD >/dev/null 2>&1
 *
 * OpenShorts registers scheduled/published posts via:
 *   POST https://example.com/uploadpost_podcast_dm_relay.php?action=register
 *
 * Authenticated diagnostics:
 *   POST {"action":"health","password":"..."}
 *   POST {"action":"status","password":"...","openshorts_job_id":"...","include_posts":"true"}
 *
 * Upload-Post comment private replies are currently documented for Instagram.
 * Other platforms are stored but skipped until Upload-Post exposes equivalent endpoints.
 */

$CONFIG = [
    'relay_password' => getenv('PODCAST_DM_RELAY_PASSWORD') ?: 'CHANGE_ME',
    'upload_post_api_key' => getenv('UPLOAD_POST_API_KEY') ?: '',
    'upload_post_api_keys_by_profile' => [
        // 'anna' => 'up_xxx',
    ],
    'upload_post_base_url' => 'https://api.upload-post.com/api/uploadposts',
    'data_dir' => __DIR__ . '/podcast_dm_relay_data',
    'supported_comment_platforms' => ['instagram'],
    'ignore_own_comments' => true,
    // Add the real Instagram handle here only when it differs from the
    // Upload-Post profile name. The automatic CTA-text guard still works
    // without this mapping.
    'own_comment_usernames_by_profile' => [
        // 'anna' => ['actual_instagram_handle'],
    ],
    // Campaign storage is cheap. API pressure is controlled separately by
    // the dynamic cron batch, so many links can remain active without request bursts.
    'max_active_link_campaigns_per_profile' => 250,
    // Eligible posts are checked on every two-minute run. Far-future schedules
    // and posts outside Instagram's private-reply window are excluded below.
    'cron_interval_minutes' => 2,
    'target_full_scan_minutes' => 2,
    'max_posts_per_cron_hard_cap' => 500,
    'scheduled_activation_lead_minutes' => 10,
    'comment_monitor_days' => 7,
    'max_comment_pages_per_post' => 3,
    'comments_per_page' => 50,
    'private_reply_template' => 'Hey du, danke für deinen Kommentar! Hier der Link zur neuen Podcastfolge, einfach hier klicken: <link> Viel Freude!',
    'public_replies' => [
        'Ist raus, check deine Nachrichtenanfragen :)',
        'Habs dir gesendet, schau mal in deine DM-Anfragen',
        'Kommt direkt zu dir, schau kurz in deine Nachrichtenanfragen.',
        'Hab dir den Link geschickt :)',
        'Hab dir geschrieben',
        'Link ist in deinem Postfach :)',
    ],
];

function respond_json(array $payload, int $statusCode = 200): void
{
    if (PHP_SAPI !== 'cli') {
        http_response_code($statusCode);
        header('Content-Type: application/json; charset=utf-8');
    }
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT) . PHP_EOL;
    exit($statusCode >= 400 ? 1 : 0);
}

function ensure_data_dir(array $config): void
{
    if (!is_dir($config['data_dir'])) {
        mkdir($config['data_dir'], 0750, true);
    }
}

function data_path(array $config, string $name): string
{
    ensure_data_dir($config);
    return rtrim($config['data_dir'], '/') . '/' . $name;
}

function load_json_file(string $path, array $fallback): array
{
    if (!is_file($path)) {
        return $fallback;
    }
    $raw = file_get_contents($path);
    if ($raw === false || trim($raw) === '') {
        return $fallback;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : $fallback;
}

function save_json_file(string $path, array $data): void
{
    $tmp = tempnam(dirname($path), basename($path) . '.tmp.');
    if ($tmp === false) {
        throw new RuntimeException('Could not create temporary JSON file.');
    }
    $json = json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    if ($json === false || file_put_contents($tmp, $json, LOCK_EX) === false || !rename($tmp, $path)) {
        @unlink($tmp);
        throw new RuntimeException('Could not save JSON file atomically.');
    }
}

function acquire_data_lock(array $config, string $name)
{
    $lock = fopen(data_path($config, $name . '.lock'), 'c');
    if (!$lock || !flock($lock, LOCK_EX)) {
        if (is_resource($lock)) {
            fclose($lock);
        }
        throw new RuntimeException('Could not acquire data lock: ' . $name);
    }
    return $lock;
}

function release_data_lock($lock): void
{
    if (is_resource($lock)) {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

function append_log(array $config, array $entry): void
{
    $entry['ts'] = gmdate('c');
    file_put_contents(
        data_path($config, 'relay.log.jsonl'),
        json_encode($entry, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL,
        FILE_APPEND | LOCK_EX
    );
}

function utf8_substr_safe(string $value, int $start, int $length): string
{
    if (function_exists('mb_substr')) {
        return mb_substr($value, $start, $length, 'UTF-8');
    }
    return substr($value, $start, $length);
}

function utf8_lower_safe(string $value): string
{
    if (function_exists('mb_strtolower')) {
        return mb_strtolower($value, 'UTF-8');
    }
    return strtolower($value);
}

function str_contains_safe(string $haystack, string $needle): bool
{
    return $needle === '' || strpos($haystack, $needle) !== false;
}

function str_ends_with_safe(string $haystack, string $needle): bool
{
    if ($needle === '') {
        return true;
    }
    return substr($haystack, -strlen($needle)) === $needle;
}

function request_payload(): array
{
    if (PHP_SAPI === 'cli') {
        return [];
    }
    $raw = file_get_contents('php://input') ?: '';
    $json = json_decode($raw, true);
    return is_array($json) ? $json : $_POST;
}

function request_action(array $payload): string
{
    if (PHP_SAPI === 'cli') {
        global $argv;
        return strtolower((string)($argv[1] ?? 'cron'));
    }
    return strtolower((string)($_GET['action'] ?? $payload['action'] ?? 'cron'));
}

function request_password(array $payload): string
{
    if (PHP_SAPI === 'cli') {
        global $argv;
        return (string)($argv[2] ?? '');
    }
    return (string)($_GET['password'] ?? $payload['password'] ?? ($_SERVER['HTTP_X_RELAY_PASSWORD'] ?? ''));
}

function assert_auth(array $config, array $payload): void
{
    $expected = (string)$config['relay_password'];
    $given = request_password($payload);
    if ($expected === '' || $expected === 'CHANGE_ME') {
        respond_json(['success' => false, 'error' => 'Configure relay_password first.'], 500);
    }
    if (!hash_equals($expected, $given)) {
        respond_json(['success' => false, 'error' => 'Unauthorized.'], 401);
    }
}

function str_clean(string $value, int $maxLen = 500): string
{
    $value = trim(preg_replace('/\s+/u', ' ', $value) ?? '');
    return utf8_substr_safe($value, 0, $maxLen);
}

function normalize_keyword(string $value): string
{
    $value = trim($value);
    if ($value === '') {
        $value = 'Video';
    }
    return utf8_substr_safe($value, 0, 40);
}

function youtube_id_from_value(string $value): string
{
    $value = trim($value);
    if (preg_match('/^[A-Za-z0-9_-]{6,20}$/', $value)) {
        return $value;
    }
    $parts = parse_url($value);
    if (!is_array($parts)) {
        return '';
    }
    $host = strtolower((string)($parts['host'] ?? ''));
    $path = (string)($parts['path'] ?? '');
    if (str_ends_with_safe($host, 'youtu.be')) {
        $candidate = trim(explode('/', trim($path, '/'))[0] ?? '');
        return preg_match('/^[A-Za-z0-9_-]{6,20}$/', $candidate) ? $candidate : '';
    }
    if (str_contains_safe($host, 'youtube.com')) {
        parse_str((string)($parts['query'] ?? ''), $query);
        $candidate = (string)($query['v'] ?? '');
        if (preg_match('/^[A-Za-z0-9_-]{6,20}$/', $candidate)) {
            return $candidate;
        }
        $segments = array_values(array_filter(explode('/', trim($path, '/'))));
        foreach (['shorts', 'embed', 'live'] as $marker) {
            $idx = array_search($marker, $segments, true);
            if ($idx !== false && isset($segments[$idx + 1]) && preg_match('/^[A-Za-z0-9_-]{6,20}$/', $segments[$idx + 1])) {
                return $segments[$idx + 1];
            }
        }
    }
    return '';
}

function normalize_destination_url(string $value): string
{
    $value = trim($value);
    if ($value === '') {
        return '';
    }
    if (!preg_match('#^https?://#i', $value)) {
        $value = 'https://' . $value;
    }
    $parts = parse_url($value);
    if (!is_array($parts) || !in_array(strtolower((string)($parts['scheme'] ?? '')), ['http', 'https'], true)) {
        return '';
    }
    $host = strtolower(trim((string)($parts['host'] ?? '')));
    if ($host === '' || (strpos($host, '.') === false && $host !== 'localhost' && filter_var($host, FILTER_VALIDATE_IP) === false)) {
        return '';
    }
    return $value;
}

function destination_id_from_url(string $url): string
{
    $youtubeId = youtube_id_from_value($url);
    return $youtubeId !== '' ? $youtubeId : substr(sha1($url), 0, 20);
}

function normalize_text_for_keyword(string $value): string
{
    $value = utf8_lower_safe($value);
    $translit = function_exists('iconv') ? @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $value) : false;
    if (is_string($translit) && $translit !== '') {
        $value = $translit;
    }
    $value = preg_replace('/[^a-z0-9]+/i', ' ', $value) ?? '';
    return trim(preg_replace('/\s+/', ' ', $value) ?? '');
}

function comment_contains_keyword(string $comment, string $keyword): bool
{
    $normalizedComment = ' ' . normalize_text_for_keyword($comment) . ' ';
    $normalizedKeyword = normalize_text_for_keyword($keyword);
    if ($normalizedKeyword === '') {
        return false;
    }
    return str_contains_safe($normalizedComment, ' ' . $normalizedKeyword . ' ');
}

function profile_api_key(array $config, string $profile): string
{
    $byProfile = $config['upload_post_api_keys_by_profile'] ?? [];
    if (is_array($byProfile) && !empty($byProfile[$profile])) {
        return (string)$byProfile[$profile];
    }
    return (string)($config['upload_post_api_key'] ?? '');
}

function upload_post_request(array $config, string $apiKey, string $method, string $path, array $params = [], ?array $json = null): array
{
    $url = rtrim($config['upload_post_base_url'], '/') . $path;
    if ($params) {
        $url .= '?' . http_build_query($params);
    }

    $headers = [
        'Authorization: Apikey ' . $apiKey,
        'Accept: application/json',
    ];
    $body = null;
    if ($json !== null) {
        $body = json_encode($json, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        $headers[] = 'Content-Type: application/json';
    }

    if (!function_exists('curl_init')) {
        $context = stream_context_create([
            'http' => [
                'method' => strtoupper($method),
                'header' => implode("\r\n", $headers),
                'content' => $body ?? '',
                'timeout' => 35,
                'ignore_errors' => true,
            ],
        ]);
        $raw = @file_get_contents($url, false, $context);
        $status = 0;
        foreach (($http_response_header ?? []) as $headerLine) {
            if (preg_match('/^HTTP\/\S+\s+(\d+)/', $headerLine, $match)) {
                $status = (int)$match[1];
                break;
            }
        }
        if ($raw === false) {
            return ['ok' => false, 'status' => $status, 'error' => 'HTTP request failed', 'json' => null, 'raw' => ''];
        }
        $decoded = json_decode((string)$raw, true);
        return [
            'ok' => $status >= 200 && $status < 300,
            'status' => $status,
            'error' => $status >= 400 ? (string)$raw : '',
            'json' => is_array($decoded) ? $decoded : null,
            'raw' => (string)$raw,
        ];
    }

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => strtoupper($method),
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 35,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
    }
    $raw = curl_exec($ch);
    $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    if ($raw === false || $error) {
        return ['ok' => false, 'status' => 0, 'error' => $error ?: 'curl error', 'json' => null, 'raw' => ''];
    }
    $decoded = json_decode((string)$raw, true);
    return [
        'ok' => $status >= 200 && $status < 300,
        'status' => $status,
        'error' => $status >= 400 ? (string)$raw : '',
        'json' => is_array($decoded) ? $decoded : null,
        'raw' => (string)$raw,
    ];
}

function extract_platform_results(array $payload): array
{
    $results = $payload['platform_results'] ?? $payload['results'] ?? [];
    $normalized = [];
    if (is_array($results)) {
        foreach ($results as $platform => $item) {
            if (is_array($item)) {
                if (!isset($item['platform']) && is_string($platform)) {
                    $item['platform'] = $platform;
                }
                $normalized[] = $item;
            }
        }
    }
    return $normalized;
}

function update_pending_post_from_status(array $config, array &$post, string $apiKey): bool
{
    if (($post['post_id'] ?? '') !== '' || ($post['post_url'] ?? '') !== '') {
        return false;
    }
    $params = [];
    if (!empty($post['request_id'])) {
        $params['request_id'] = $post['request_id'];
    }
    if (!empty($post['vendor_job_id'])) {
        $params['job_id'] = $post['vendor_job_id'];
    }
    if (!$params) {
        return false;
    }
    $response = upload_post_request($config, $apiKey, 'GET', '/status', $params);
    if (!$response['ok'] || !is_array($response['json'])) {
        return false;
    }
    $platform = strtolower((string)($post['platform'] ?? ''));
    foreach (extract_platform_results($response['json']) as $result) {
        if (strtolower((string)($result['platform'] ?? '')) !== $platform) {
            continue;
        }
        $post['post_id'] = str_clean((string)($result['post_id'] ?? $result['platform_post_id'] ?? $result['publish_id'] ?? ''), 200);
        $post['post_url'] = str_clean((string)($result['url'] ?? $result['link'] ?? $result['permalink'] ?? ''), 500);
        $post['status'] = str_clean((string)($result['status'] ?? $response['json']['status'] ?? ''), 80);
        $post['updated_at'] = gmdate('c');
        return true;
    }
    return false;
}

function extract_comments(array $payload): array
{
    $comments = [];
    $seen = [];
    $walk = function (array $items, int $depth = 0) use (&$comments, &$seen, &$walk): void {
        if ($depth > 4) {
            return;
        }
        foreach ($items as $item) {
            if (!is_array($item)) {
                continue;
            }
            $id = comment_id($item);
            $dedupeKey = $id !== '' ? $id : sha1(json_encode($item));
            if (!isset($seen[$dedupeKey])) {
                $seen[$dedupeKey] = true;
                $comments[] = $item;
            }
            foreach (['replies', 'children', 'comments', 'data', 'items', 'results'] as $nestedKey) {
                if (isset($item[$nestedKey]) && is_array($item[$nestedKey])) {
                    $nested = $item[$nestedKey];
                    if (isset($nested['data']) && is_array($nested['data'])) {
                        $nested = $nested['data'];
                    }
                    $walk($nested, $depth + 1);
                }
            }
        }
    };

    foreach (['comments', 'data', 'items', 'results'] as $key) {
        if (isset($payload[$key]) && is_array($payload[$key])) {
            $walk($payload[$key]);
            return $comments;
        }
    }
    $keys = array_keys($payload);
    $isList = $keys === array_filter($keys, 'is_int');
    if ($isList) {
        $walk($payload);
        return $comments;
    }
    return [];
}

function extract_pagination(array $payload): array
{
    $pagination = $payload['pagination'] ?? $payload['paging'] ?? [];
    if (!is_array($pagination)) {
        return ['has_next' => false, 'next_cursor' => null];
    }
    $next = $pagination['next_cursor'] ?? $pagination['after'] ?? ($pagination['cursors']['after'] ?? null);
    $hasNext = (bool)($pagination['has_next'] ?? $pagination['has_next_page'] ?? $next);
    return ['has_next' => $hasNext, 'next_cursor' => $next ? (string)$next : null];
}

function comment_id(array $comment): string
{
    return str_clean((string)($comment['id'] ?? $comment['comment_id'] ?? ''), 200);
}

function comment_text(array $comment): string
{
    return (string)($comment['text'] ?? $comment['message'] ?? $comment['caption'] ?? '');
}

function normalize_profile_identity(string $value): string
{
    $value = trim($value);
    if ($value === '') {
        return '';
    }
    $parts = parse_url($value);
    if (is_array($parts) && !empty($parts['host'])) {
        $segments = array_values(array_filter(explode('/', trim((string)($parts['path'] ?? ''), '/'))));
        $value = (string)($segments[0] ?? '');
    }
    return utf8_lower_safe(ltrim(trim($value), '@'));
}

function comment_author_username(array $comment): string
{
    foreach (['username', 'author_username', 'commenter_username', 'from_username', 'owner_username'] as $key) {
        if (!empty($comment[$key]) && is_scalar($comment[$key])) {
            return str_clean((string)$comment[$key], 200);
        }
    }
    foreach (['user', 'author', 'commenter', 'from', 'owner', 'profile'] as $containerKey) {
        $container = $comment[$containerKey] ?? null;
        if (is_string($container) && trim($container) !== '') {
            return str_clean($container, 200);
        }
        if (!is_array($container)) {
            continue;
        }
        foreach (['username', 'user_name', 'handle', 'name'] as $key) {
            if (!empty($container[$key]) && is_scalar($container[$key])) {
                return str_clean((string)$container[$key], 200);
            }
        }
    }
    return '';
}

function own_comment_usernames(array $config, array $campaign): array
{
    $profile = (string)($campaign['profile_username'] ?? '');
    $values = [$profile];
    $configured = $config['own_comment_usernames_by_profile'] ?? [];
    if (is_array($configured)) {
        foreach ($configured as $configuredProfile => $usernames) {
            if (strcasecmp((string)$configuredProfile, $profile) !== 0) {
                continue;
            }
            foreach ((array)$usernames as $username) {
                $values[] = (string)$username;
            }
        }
    }
    foreach ((array)($campaign['own_comment_usernames'] ?? []) as $username) {
        $values[] = (string)$username;
    }
    $normalized = array_values(array_filter(array_map('normalize_profile_identity', $values)));
    return array_values(array_unique($normalized));
}

function render_campaign_comment_cta(array $campaign): string
{
    $keyword = normalize_keyword((string)($campaign['keyword'] ?? 'Video'));
    $template = trim((string)($campaign['comment_template'] ?? ''));
    if ($template === '') {
        $template = 'Kommentiere "<keyword>" und wir senden dir den Link zum Podcast zu';
    }
    return preg_replace('/<keyword>/i', $keyword, $template) ?? '';
}

function normalized_comment_text(string $value): string
{
    return normalize_text_for_keyword($value);
}

function comment_ignore_reason(array $config, array $campaign, array $post, array $comment): ?string
{
    if (empty($config['ignore_own_comments'])) {
        return null;
    }

    $author = normalize_profile_identity(comment_author_username($comment));
    if ($author !== '' && in_array($author, own_comment_usernames($config, $campaign), true)) {
        return 'own_author';
    }

    $normalizedText = normalized_comment_text(comment_text($comment));
    if ($normalizedText === '') {
        return null;
    }

    $registeredFirstComment = normalized_comment_text((string)($post['own_first_comment'] ?? ''));
    if ($registeredFirstComment !== '' && $normalizedText === $registeredFirstComment) {
        return 'registered_first_comment';
    }

    // Older registrations do not have own_first_comment. Matching the campaign
    // CTA as a complete phrase protects those posts without relying on an author.
    $normalizedCta = normalized_comment_text(render_campaign_comment_cta($campaign));
    $ctaWordCount = count(array_filter(explode(' ', $normalizedCta)));
    if ($ctaWordCount >= 4 && str_contains_safe(' ' . $normalizedText . ' ', ' ' . $normalizedCta . ' ')) {
        return 'campaign_cta';
    }
    return null;
}

function apply_profile_campaign_limits(array $config, array &$registry): void
{
    $limit = max(1, (int)($config['max_active_link_campaigns_per_profile'] ?? 250));
    $byProfile = [];
    foreach ($registry['campaigns'] ?? [] as $key => $item) {
        $profile = (string)($item['profile_username'] ?? '');
        $byProfile[$profile][] = [
            'key' => (string)$key,
            'updated_at' => strtotime((string)($item['updated_at'] ?? $item['created_at'] ?? '')) ?: 0,
        ];
    }

    foreach ($byProfile as $items) {
        usort($items, static fn(array $a, array $b): int => $b['updated_at'] <=> $a['updated_at']);
        foreach ($items as $index => $item) {
            $key = $item['key'];
            if (!isset($registry['campaigns'][$key])) {
                continue;
            }
            if ($index < $limit) {
                if (($registry['campaigns'][$key]['inactive_reason'] ?? '') === 'profile_recent_limit') {
                    $registry['campaigns'][$key]['active'] = true;
                    unset($registry['campaigns'][$key]['inactive_reason']);
                }
                continue;
            }
            $registry['campaigns'][$key]['active'] = false;
            $registry['campaigns'][$key]['inactive_reason'] = 'profile_recent_limit';
        }
    }
}

function load_registry_snapshot(array $config): array
{
    $lock = acquire_data_lock($config, 'registry');
    $registry = load_json_file(data_path($config, 'registry.json'), ['campaigns' => []]);
    release_data_lock($lock);
    return $registry;
}

function request_filter_value(array $payload, string $key, string $fallback = ''): string
{
    if (PHP_SAPI === 'cli') {
        return $fallback;
    }
    return str_clean((string)($_GET[$key] ?? $payload[$key] ?? $fallback), 200);
}

function last_log_event(array $config, string $eventName): ?array
{
    $path = data_path($config, 'relay.log.jsonl');
    if (!is_file($path) || filesize($path) === 0) {
        return null;
    }
    $handle = fopen($path, 'rb');
    if (!$handle) {
        return null;
    }
    $size = filesize($path) ?: 0;
    fseek($handle, max(0, $size - 65536));
    $tail = stream_get_contents($handle) ?: '';
    fclose($handle);
    $lines = array_reverse(array_filter(explode("\n", $tail)));
    foreach ($lines as $line) {
        $entry = json_decode($line, true);
        if (is_array($entry) && ($entry['event'] ?? '') === $eventName) {
            return $entry;
        }
    }
    return null;
}

function build_registry_status(array $config, array $payload, bool $includeCampaigns): array
{
    $registry = load_registry_snapshot($config);
    $profileFilter = request_filter_value($payload, 'profile_username', request_filter_value($payload, 'profile'));
    $jobFilter = request_filter_value($payload, 'openshorts_job_id', request_filter_value($payload, 'job_id'));
    $linkFilter = request_filter_value($payload, 'link_id');
    $profiles = [];
    $campaignDetails = [];
    $totals = [
        'campaigns' => 0,
        'active_campaigns' => 0,
        'posts' => 0,
        'resolved_posts' => 0,
        'waiting_posts' => 0,
        'checked_posts' => 0,
    ];

    foreach ($registry['campaigns'] ?? [] as $campaignKey => $campaign) {
        $profile = (string)($campaign['profile_username'] ?? '');
        if ($profileFilter !== '' && strcasecmp($profileFilter, $profile) !== 0) {
            continue;
        }
        if ($linkFilter !== '' && $linkFilter !== (string)($campaign['link_id'] ?? $campaign['youtube_id'] ?? '')) {
            continue;
        }
        $posts = [];
        foreach ($campaign['posts'] ?? [] as $postKey => $post) {
            if ($jobFilter !== '' && $jobFilter !== (string)($post['openshorts_job_id'] ?? '')) {
                continue;
            }
            $posts[$postKey] = $post;
        }
        if ($jobFilter !== '' && !$posts) {
            continue;
        }

        $active = !empty($campaign['active']);
        if (!isset($profiles[$profile]) || !is_array($profiles[$profile])) {
            $profiles[$profile] = ['campaigns' => 0, 'active_campaigns' => 0, 'posts' => 0, 'resolved_posts' => 0, 'waiting_posts' => 0];
        }
        $profileStats =& $profiles[$profile];
        $totals['campaigns']++;
        $profileStats['campaigns']++;
        if ($active) {
            $totals['active_campaigns']++;
            $profileStats['active_campaigns']++;
        }
        foreach ($posts as $post) {
            $resolved = (string)($post['post_id'] ?? '') !== '' || (string)($post['post_url'] ?? '') !== '';
            $totals['posts']++;
            $profileStats['posts']++;
            if ($resolved) {
                $totals['resolved_posts']++;
                $profileStats['resolved_posts']++;
            } else {
                $totals['waiting_posts']++;
                $profileStats['waiting_posts']++;
            }
            if (!empty($post['last_checked_at'])) {
                $totals['checked_posts']++;
            }
        }
        unset($profileStats);

        if ($includeCampaigns) {
            $detail = [
                'campaign_key' => (string)$campaignKey,
                'profile_username' => $profile,
                'link_id' => (string)($campaign['link_id'] ?? $campaign['youtube_id'] ?? ''),
                'link_url' => (string)($campaign['link_url'] ?? $campaign['youtube_url'] ?? ''),
                'keyword' => (string)($campaign['keyword'] ?? ''),
                'active' => $active,
                'post_count' => count($posts),
                'created_at' => $campaign['created_at'] ?? null,
                'updated_at' => $campaign['updated_at'] ?? null,
            ];
            $includePostsValue = strtolower(request_filter_value($payload, 'include_posts'));
            if (in_array($includePostsValue, ['1', 'true', 'yes', 'on'], true)) {
                $detail['posts'] = array_values($posts);
            }
            $campaignDetails[] = $detail;
        }
    }

    ksort($profiles);
    return [
        'filters' => [
            'profile_username' => $profileFilter ?: null,
            'openshorts_job_id' => $jobFilter ?: null,
            'link_id' => $linkFilter ?: null,
        ],
        'totals' => $totals,
        'profiles' => $profiles,
        'campaigns' => $includeCampaigns ? $campaignDetails : null,
    ];
}

function handle_health(array $config, array $payload): void
{
    ensure_data_dir($config);
    $status = build_registry_status($config, $payload, false);
    $processed = load_json_file(data_path($config, 'processed.json'), []);
    $profileApiKeys = array_filter(
        is_array($config['upload_post_api_keys_by_profile'] ?? null) ? $config['upload_post_api_keys_by_profile'] : [],
        static fn($value): bool => trim((string)$value) !== ''
    );
    respond_json([
        'success' => true,
        'status' => 'ok',
        'checked_at' => gmdate('c'),
        'storage' => [
            'data_dir' => $config['data_dir'],
            'writable' => is_writable($config['data_dir']),
            'registry_exists' => is_file(data_path($config, 'registry.json')),
            'processed_comments' => count($processed),
        ],
        'configuration' => [
            'upload_post_api_key_configured' => (string)($config['upload_post_api_key'] ?? '') !== '' || count($profileApiKeys) > 0,
            'profile_api_keys_configured' => count($profileApiKeys),
            'active_campaign_limit_per_profile' => (int)$config['max_active_link_campaigns_per_profile'],
            'cron_interval_minutes' => (int)$config['cron_interval_minutes'],
            'target_full_scan_minutes' => (int)$config['target_full_scan_minutes'],
            'scheduled_activation_lead_minutes' => (int)$config['scheduled_activation_lead_minutes'],
            'comment_monitor_days' => (int)$config['comment_monitor_days'],
            'max_posts_per_cron_hard_cap' => (int)$config['max_posts_per_cron_hard_cap'],
            'ignore_own_comments' => !empty($config['ignore_own_comments']),
            'own_comment_profile_mappings' => count(
                is_array($config['own_comment_usernames_by_profile'] ?? null)
                    ? $config['own_comment_usernames_by_profile']
                    : []
            ),
        ],
        'registry' => $status,
        'last_cron' => last_log_event($config, 'cron'),
        'last_registration' => last_log_event($config, 'register'),
    ]);
}

function handle_status(array $config, array $payload): void
{
    respond_json([
        'success' => true,
        'checked_at' => gmdate('c'),
        'registry' => build_registry_status($config, $payload, true),
    ]);
}

function handle_register(array $config, array $payload): void
{
    $profile = str_clean((string)($payload['profile_username'] ?? $payload['profile'] ?? ''), 120);
    $linkUrl = normalize_destination_url((string)($payload['link_url'] ?? $payload['destination_url'] ?? $payload['youtube_url'] ?? ''));
    $linkId = str_clean((string)($payload['link_id'] ?? ''), 80);
    if ($linkId === '' && $linkUrl !== '') {
        $linkId = destination_id_from_url($linkUrl);
    }
    if ($profile === '' || $linkUrl === '' || $linkId === '') {
        respond_json(['success' => false, 'error' => 'profile_username and a valid link_url are required.'], 400);
    }
    $youtubeId = youtube_id_from_value((string)($payload['youtube_id'] ?? $linkUrl));
    $youtubeUrl = $youtubeId !== '' ? 'https://youtu.be/' . $youtubeId : '';
    $keyword = normalize_keyword((string)($payload['keyword'] ?? 'Video'));
    $posts = is_array($payload['posts'] ?? null) ? $payload['posts'] : [];
    if (!$posts) {
        respond_json(['success' => false, 'error' => 'posts array is required.'], 400);
    }

    $registryPath = data_path($config, 'registry.json');
    $registryLock = acquire_data_lock($config, 'registry');
    $registry = load_json_file($registryPath, ['campaigns' => []]);
    $campaignKey = $profile . ':' . $linkId;
    $campaign = $registry['campaigns'][$campaignKey] ?? [
        'profile_username' => $profile,
        'link_id' => $linkId,
        'link_url' => $linkUrl,
        'posts' => [],
        'created_at' => gmdate('c'),
    ];
    $campaign['link_id'] = $linkId;
    $campaign['link_url'] = $linkUrl;
    $campaign['youtube_id'] = $youtubeId;
    $campaign['youtube_url'] = $youtubeUrl;
    $campaign['keyword'] = $keyword;
    $campaign['comment_template'] = str_clean((string)($payload['comment_template'] ?? $campaign['comment_template'] ?? ''), 1000);
    $campaign['active'] = true;
    $campaign['dm_message'] = str_clean((string)($payload['dm_message'] ?? str_replace('<link>', $linkUrl, $config['private_reply_template'])), 1000);
    $campaign['public_replies'] = is_array($payload['public_replies'] ?? null) && $payload['public_replies']
        ? array_values(array_map(fn($item) => str_clean((string)$item, 300), $payload['public_replies']))
        : $config['public_replies'];
    $campaign['updated_at'] = gmdate('c');
    $ownFirstComment = str_clean((string)($payload['own_first_comment'] ?? ''), 2200);

    $replacesVendorJobId = str_clean((string)($payload['replaces_vendor_job_id'] ?? ''), 200);
    $replacedPostCount = 0;
    if ($replacesVendorJobId !== '') {
        foreach ($campaign['posts'] ?? [] as $existingPostKey => $existingPost) {
            if ((string)($existingPost['vendor_job_id'] ?? '') !== $replacesVendorJobId) {
                continue;
            }
            unset($campaign['posts'][$existingPostKey]);
            $replacedPostCount++;
        }
    }

    foreach ($posts as $rawPost) {
        if (!is_array($rawPost)) {
            continue;
        }
        $platform = strtolower(str_clean((string)($rawPost['platform'] ?? ''), 50));
        if ($platform === '') {
            continue;
        }
        $postId = str_clean((string)($rawPost['post_id'] ?? ''), 200);
        $postUrl = str_clean((string)($rawPost['post_url'] ?? $rawPost['url'] ?? ''), 500);
        $vendorJobId = str_clean((string)($payload['vendor_job_id'] ?? $rawPost['vendor_job_id'] ?? ''), 200);
        $requestId = str_clean((string)($payload['request_id'] ?? $rawPost['request_id'] ?? ''), 200);
        $postKey = $platform . ':' . ($postId ?: $postUrl ?: $vendorJobId ?: $requestId ?: sha1(json_encode($rawPost)));
        $existing = $campaign['posts'][$postKey] ?? [];
        $campaign['posts'][$postKey] = array_filter([
            'platform' => $platform,
            'post_id' => $postId ?: ($existing['post_id'] ?? ''),
            'post_url' => $postUrl ?: ($existing['post_url'] ?? ''),
            'vendor_job_id' => $vendorJobId ?: ($existing['vendor_job_id'] ?? ''),
            'request_id' => $requestId ?: ($existing['request_id'] ?? ''),
            'status' => str_clean((string)($rawPost['status'] ?? $payload['status'] ?? $existing['status'] ?? ''), 80),
            'openshorts_job_id' => str_clean((string)($payload['openshorts_job_id'] ?? $existing['openshorts_job_id'] ?? ''), 120),
            'clip_index' => $payload['clip_index'] ?? ($existing['clip_index'] ?? null),
            'clip_title' => str_clean((string)($payload['clip_title'] ?? $existing['clip_title'] ?? ''), 300),
            'scheduled_date' => str_clean((string)($payload['scheduled_date'] ?? $existing['scheduled_date'] ?? ''), 120),
            'own_first_comment' => $ownFirstComment ?: ($existing['own_first_comment'] ?? ''),
            'created_at' => $existing['created_at'] ?? gmdate('c'),
            'updated_at' => gmdate('c'),
        ], fn($value) => $value !== null && $value !== '');
    }

    $registry['campaigns'][$campaignKey] = $campaign;

    apply_profile_campaign_limits($config, $registry);

    save_json_file($registryPath, $registry);
    release_data_lock($registryLock);
    $campaignPostCount = count($campaign['posts']);
    append_log($config, [
        'event' => 'register',
        'profile' => $profile,
        'link_id' => $linkId,
        'accepted_post_count' => count($posts),
        'campaign_post_count' => $campaignPostCount,
        'replaced_vendor_job_id' => $replacesVendorJobId ?: null,
        'replaced_post_count' => $replacedPostCount,
    ]);
    respond_json([
        'success' => true,
        'campaign_key' => $campaignKey,
        'profile_username' => $profile,
        'link_id' => $linkId,
        'accepted_post_count' => count($posts),
        'campaign_post_count' => $campaignPostCount,
        'replaced_vendor_job_id' => $replacesVendorJobId ?: null,
        'replaced_post_count' => $replacedPostCount,
        'registered_at' => gmdate('c'),
    ]);
}

function process_post_comments(array $config, array $campaign, array &$post, array &$processed, string $apiKey): array
{
    $platform = strtolower((string)($post['platform'] ?? ''));
    if (!in_array($platform, $config['supported_comment_platforms'], true)) {
        return ['checked' => 0, 'matched' => 0, 'replied' => 0, 'skipped' => 'unsupported_platform'];
    }
    if (($post['post_id'] ?? '') === '' && ($post['post_url'] ?? '') === '') {
        update_pending_post_from_status($config, $post, $apiKey);
    }
    if (($post['post_id'] ?? '') === '' && ($post['post_url'] ?? '') === '') {
        return ['checked' => 0, 'matched' => 0, 'replied' => 0, 'skipped' => 'waiting_for_post_id'];
    }

    $profile = (string)$campaign['profile_username'];
    $keyword = (string)$campaign['keyword'];
    $replyMessage = str_replace('<link>', (string)($campaign['link_url'] ?? $campaign['youtube_url'] ?? ''), (string)($campaign['dm_message'] ?? $config['private_reply_template']));
    $publicReplies = is_array($campaign['public_replies'] ?? null) && $campaign['public_replies'] ? $campaign['public_replies'] : $config['public_replies'];

    $checked = 0;
    $matched = 0;
    $replied = 0;
    $ignoredOwnComments = 0;
    $after = null;
    for ($page = 0; $page < (int)$config['max_comment_pages_per_post']; $page++) {
        $params = [
            'platform' => $platform,
            'user' => $profile,
            'limit' => (int)$config['comments_per_page'],
        ];
        if (($post['post_id'] ?? '') !== '') {
            $params['post_id'] = (string)$post['post_id'];
        } else {
            $params['post_url'] = (string)$post['post_url'];
        }
        if ($after) {
            $params['after'] = $after;
        }
        $response = upload_post_request($config, $apiKey, 'GET', '/comments', $params);
        if (!$response['ok'] || !is_array($response['json'])) {
            return [
                'checked' => $checked,
                'matched' => $matched,
                'replied' => $replied,
                'ignored_own_comments' => $ignoredOwnComments,
                'error' => $response['error'] ?: $response['raw'],
                'rate_limited' => (int)($response['status'] ?? 0) === 429,
            ];
        }
        foreach (extract_comments($response['json']) as $comment) {
            if (!is_array($comment)) {
                continue;
            }
            $checked++;
            $commentId = comment_id($comment);
            if ($commentId === '') {
                continue;
            }
            $processedKey = $profile . ':' . $platform . ':' . $commentId;
            if (isset($processed[$processedKey])) {
                continue;
            }
            $ignoreReason = comment_ignore_reason($config, $campaign, $post, $comment);
            if ($ignoreReason !== null) {
                $processed[$processedKey] = [
                    'profile_username' => $profile,
                    'platform' => $platform,
                    'comment_id' => $commentId,
                    'post_id' => (string)($post['post_id'] ?? ''),
                    'post_url' => (string)($post['post_url'] ?? ''),
                    'comment_author' => comment_author_username($comment),
                    'ignored' => true,
                    'ignore_reason' => $ignoreReason,
                    'processed_at' => gmdate('c'),
                ];
                $ignoredOwnComments++;
                continue;
            }
            if (!comment_contains_keyword(comment_text($comment), $keyword)) {
                continue;
            }
            $matched++;

            $dm = upload_post_request($config, $apiKey, 'POST', '/comments/reply', [], [
                'platform' => $platform,
                'user' => $profile,
                'comment_id' => $commentId,
                'message' => $replyMessage,
            ]);
            if ($dm['status'] === 429) {
                return [
                    'checked' => $checked,
                    'matched' => $matched,
                    'replied' => $replied,
                    'ignored_own_comments' => $ignoredOwnComments,
                    'rate_limited' => true,
                ];
            }

            // Persist the reservation before the public reply. Public replies are
            // visible and not idempotent at Upload-Post/Instagram level; if the
            // request succeeds but this process times out before the final save,
            // the next cron must not post the same visible reply again.
            $processed[$processedKey] = [
                'profile_username' => $profile,
                'platform' => $platform,
                'comment_id' => $commentId,
                'post_id' => (string)($post['post_id'] ?? ''),
                'post_url' => (string)($post['post_url'] ?? ''),
                'keyword' => $keyword,
                'link_id' => (string)($campaign['link_id'] ?? $campaign['youtube_id'] ?? ''),
                'youtube_id' => (string)($campaign['youtube_id'] ?? ''),
                'dm_status' => $dm['status'],
                'public_status' => null,
                'ok' => $dm['ok'],
                'reserved_before_public_reply' => true,
                'processed_at' => gmdate('c'),
            ];
            save_json_file(data_path($config, 'processed.json'), $processed);

            $publicMessage = (string)$publicReplies[array_rand($publicReplies)];
            $public = upload_post_request($config, $apiKey, 'POST', '/comments/public-reply', [], [
                'platform' => $platform,
                'user' => $profile,
                'comment_id' => $commentId,
                'message' => $publicMessage,
            ]);

            $processed[$processedKey]['public_status'] = $public['status'];
            $processed[$processedKey]['public_reply_attempted_at'] = gmdate('c');
            $processed[$processedKey]['public_reply_message'] = $publicMessage;
            if ($dm['ok']) {
                $replied++;
            }
        }
        $pagination = extract_pagination($response['json']);
        if (!$pagination['has_next'] || !$pagination['next_cursor']) {
            break;
        }
        $after = $pagination['next_cursor'];
    }
    $post['last_checked_at'] = gmdate('c');
    return [
        'checked' => $checked,
        'matched' => $matched,
        'replied' => $replied,
        'ignored_own_comments' => $ignoredOwnComments,
    ];
}

function post_is_in_comment_monitor_window(array $config, array $post, int $now): array
{
    $scheduledAt = strtotime((string)($post['scheduled_date'] ?? '')) ?: 0;
    $createdAt = strtotime((string)($post['created_at'] ?? '')) ?: 0;
    $leadSeconds = max(0, (int)($config['scheduled_activation_lead_minutes'] ?? 10)) * 60;
    $monitorSeconds = max(1, (int)($config['comment_monitor_days'] ?? 7)) * 86400;

    if ($scheduledAt > 0 && $scheduledAt > $now + $leadSeconds) {
        return ['eligible' => false, 'reason' => 'not_due_yet'];
    }

    $windowStart = $scheduledAt > 0 ? $scheduledAt : $createdAt;
    if ($windowStart > 0 && $windowStart < $now - $monitorSeconds) {
        return ['eligible' => false, 'reason' => 'dm_window_expired'];
    }

    return ['eligible' => true, 'reason' => null];
}

function handle_cron(array $config): void
{
    $registryPath = data_path($config, 'registry.json');
    $processedPath = data_path($config, 'processed.json');
    $lockPath = data_path($config, 'cron.lock');
    $lock = fopen($lockPath, 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) {
        respond_json(['success' => true, 'skipped' => 'already_running']);
    }

    $registry = load_json_file($registryPath, ['campaigns' => []]);
    $processed = load_json_file($processedPath, []);
    apply_profile_campaign_limits($config, $registry);
    $summary = [
        'campaigns' => 0,
        'posts' => 0,
        'checked' => 0,
        'matched' => 0,
        'replied' => 0,
        'ignored_own_comments' => 0,
        'not_due_yet' => 0,
        'dm_window_expired' => 0,
        'errors' => [],
    ];
    $postCandidates = [];
    $now = time();

    // Build one fair queue across every profile. Sorting by last_checked_at
    // prevents the first campaigns in registry.json from monopolizing each run.
    foreach ($registry['campaigns'] ?? [] as $campaignKey => $campaign) {
        if (empty($campaign['active'])) {
            continue;
        }
        $profile = (string)($campaign['profile_username'] ?? '');
        $apiKey = profile_api_key($config, $profile);
        if ($apiKey === '') {
            $summary['errors'][] = ['campaign' => $campaignKey, 'error' => 'missing_upload_post_api_key'];
            continue;
        }
        $summary['campaigns']++;
        foreach ($campaign['posts'] ?? [] as $postKey => $post) {
            $platform = strtolower((string)($post['platform'] ?? ''));
            if (!in_array($platform, $config['supported_comment_platforms'], true)) {
                continue;
            }
            $monitorWindow = post_is_in_comment_monitor_window($config, $post, $now);
            if (empty($monitorWindow['eligible'])) {
                $reason = (string)($monitorWindow['reason'] ?? '');
                if (array_key_exists($reason, $summary)) {
                    $summary[$reason]++;
                }
                continue;
            }
            $lastChecked = strtotime((string)($post['last_checked_at'] ?? '')) ?: 0;
            $createdAt = strtotime((string)($post['created_at'] ?? '')) ?: 0;
            $postCandidates[] = [
                'campaign_key' => (string)$campaignKey,
                'post_key' => (string)$postKey,
                'api_key' => $apiKey,
                'last_checked_at' => $lastChecked,
                'created_at' => $createdAt,
            ];
        }
    }

    usort($postCandidates, static function (array $a, array $b): int {
        $byLastCheck = $a['last_checked_at'] <=> $b['last_checked_at'];
        if ($byLastCheck !== 0) {
            return $byLastCheck;
        }
        return $a['created_at'] <=> $b['created_at'];
    });

    $cronInterval = max(1, (int)($config['cron_interval_minutes'] ?? 2));
    $targetScanInterval = max($cronInterval, (int)($config['target_full_scan_minutes'] ?? 2));
    $runsPerTarget = max(1, (int)floor($targetScanInterval / $cronInterval));
    $requiredBatchSize = (int)ceil(count($postCandidates) / $runsPerTarget);
    $hardCap = max(1, (int)($config['max_posts_per_cron_hard_cap'] ?? 500));
    $batchSize = min($hardCap, $requiredBatchSize);
    $summary['registered_posts'] = count($postCandidates);
    $summary['batch_size'] = $batchSize;
    $summary['target_scan_minutes'] = $targetScanInterval;
    $summary['target_capacity_sufficient'] = $requiredBatchSize <= $hardCap;
    if (!$summary['target_capacity_sufficient']) {
        $summary['errors'][] = [
            'error' => 'scan_target_capacity_exceeded',
            'registered_posts' => count($postCandidates),
            'max_supported_posts_for_target' => $hardCap * $runsPerTarget,
        ];
    }

    foreach (array_slice($postCandidates, 0, $batchSize) as $candidate) {
        $campaignKey = $candidate['campaign_key'];
        $postKey = $candidate['post_key'];
        if (!isset($registry['campaigns'][$campaignKey]['posts'][$postKey])) {
            continue;
        }
        $campaign =& $registry['campaigns'][$campaignKey];
        $post =& $campaign['posts'][$postKey];
        $result = process_post_comments($config, $campaign, $post, $processed, (string)$candidate['api_key']);
        // Also advance unresolved/error posts so one broken entry cannot starve
        // all later campaigns. Errors remain visible in the cron summary/log.
        $post['last_checked_at'] = gmdate('c');
        $summary['posts']++;
        $summary['checked'] += (int)($result['checked'] ?? 0);
        $summary['matched'] += (int)($result['matched'] ?? 0);
        $summary['replied'] += (int)($result['replied'] ?? 0);
        $summary['ignored_own_comments'] += (int)($result['ignored_own_comments'] ?? 0);
        if (!empty($result['error']) || !empty($result['rate_limited'])) {
            $summary['errors'][] = ['campaign' => $campaignKey, 'post' => $postKey, 'result' => $result];
        }
        $stopForRateLimit = !empty($result['rate_limited']);
        unset($post, $campaign);
        if ($stopForRateLimit) {
            break;
        }
    }

    // Registrations may arrive while the cron performs slow API requests. Merge only
    // cron-owned runtime fields into the latest registry so new posts are never lost.
    $registryLock = acquire_data_lock($config, 'registry');
    $latestRegistry = load_json_file($registryPath, ['campaigns' => []]);
    foreach ($registry['campaigns'] ?? [] as $campaignKey => $processedCampaign) {
        if (!isset($latestRegistry['campaigns'][$campaignKey])) {
            $latestRegistry['campaigns'][$campaignKey] = $processedCampaign;
            continue;
        }
        foreach ($processedCampaign['posts'] ?? [] as $postKey => $processedPost) {
            if (!isset($latestRegistry['campaigns'][$campaignKey]['posts'][$postKey])) {
                $latestRegistry['campaigns'][$campaignKey]['posts'][$postKey] = $processedPost;
                continue;
            }
            foreach (['post_id', 'post_url', 'status', 'updated_at', 'last_checked_at'] as $field) {
                if (array_key_exists($field, $processedPost)) {
                    $latestRegistry['campaigns'][$campaignKey]['posts'][$postKey][$field] = $processedPost[$field];
                }
            }
        }
    }
    $registry = $latestRegistry;
    save_json_file($registryPath, $registry);
    release_data_lock($registryLock);
    save_json_file($processedPath, $processed);
    append_log($config, ['event' => 'cron', 'summary' => $summary]);
    respond_json(['success' => true, 'summary' => $summary]);
}

if (!defined('PODCAST_DM_RELAY_LIBRARY_ONLY')) {
    $payload = request_payload();
    assert_auth($CONFIG, $payload);
    $action = request_action($payload);
    if ($action === 'register') {
        handle_register($CONFIG, $payload);
    }
    if ($action === 'health') {
        handle_health($CONFIG, $payload);
    }
    if ($action === 'status') {
        handle_status($CONFIG, $payload);
    }
    if ($action === 'cron' || $action === 'run') {
        handle_cron($CONFIG);
    }
    respond_json(['success' => false, 'error' => 'Unknown action.'], 400);
}
