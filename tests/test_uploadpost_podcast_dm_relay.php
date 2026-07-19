<?php
declare(strict_types=1);

define('PODCAST_DM_RELAY_LIBRARY_ONLY', true);
require __DIR__ . '/../scripts/uploadpost_podcast_dm_relay.php';

function assert_same($expected, $actual, string $message): void
{
    if ($expected !== $actual) {
        fwrite(STDERR, $message . PHP_EOL);
        fwrite(STDERR, 'Expected: ' . var_export($expected, true) . PHP_EOL);
        fwrite(STDERR, 'Actual:   ' . var_export($actual, true) . PHP_EOL);
        exit(1);
    }
}

$config = [
    'ignore_own_comments' => true,
    'own_comment_usernames_by_profile' => [
        'anna' => ['anna_actual'],
    ],
];
$campaign = [
    'profile_username' => 'anna',
    'keyword' => 'Video',
    'comment_template' => 'Kommentiere "<keyword>" und wir senden dir den Link zum Podcast zu',
];
$post = [
    'own_first_comment' => "Kommentiere \"Video\" und wir senden dir den Link zum Podcast zu\n\nKI-Text",
];

assert_same(
    'own_author',
    comment_ignore_reason($config, $campaign, $post, [
        'id' => '1',
        'text' => 'Video',
        'user' => ['username' => 'anna_actual'],
    ]),
    'The connected Instagram account must be ignored by author.'
);
assert_same(
    'registered_first_comment',
    comment_ignore_reason($config, $campaign, $post, [
        'id' => '2',
        'text' => $post['own_first_comment'],
        'user' => ['username' => 'someone_else'],
    ]),
    'The exact registered first comment must be ignored.'
);
assert_same(
    'campaign_cta',
    comment_ignore_reason($config, $campaign, [], [
        'id' => '3',
        'text' => 'Kommentiere Video und wir senden dir den Link zum Podcast zu. Mehr Text.',
        'user' => ['username' => 'anna_actual_but_unknown'],
    ]),
    'Legacy registrations must be protected by the campaign CTA.'
);
assert_same(
    null,
    comment_ignore_reason($config, $campaign, $post, [
        'id' => '4',
        'text' => 'Video',
        'user' => ['username' => 'real_commenter'],
    ]),
    'A real commenter using the keyword must not be ignored.'
);
$shortTemplateCampaign = $campaign;
$shortTemplateCampaign['comment_template'] = '<keyword>';
assert_same(
    null,
    comment_ignore_reason($config, $shortTemplateCampaign, [], [
        'id' => '5',
        'text' => 'Video',
        'user' => ['username' => 'real_commenter'],
    ]),
    'A short custom CTA must not suppress all ordinary keyword comments.'
);
assert_same(true, comment_contains_keyword('Bitte das VIDEO!', 'Video'), 'Keyword matching must remain active.');

echo "Relay self-comment tests passed.\n";
