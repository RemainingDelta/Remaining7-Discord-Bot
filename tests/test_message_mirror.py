from features.message_mirror import _parse_message_link, _strip_mentions


LINK = "https://discord.com/channels/111/222/333"


class TestParseMessageLink:
    def test_plain_link(self):
        assert _parse_message_link(LINK) == (111, 222, 333)

    def test_link_with_surrounding_whitespace(self):
        assert _parse_message_link(f"  {LINK}\n") == (111, 222, 333)

    def test_ptb_and_canary_links(self):
        assert _parse_message_link("https://ptb.discord.com/channels/1/2/3") == (
            1,
            2,
            3,
        )
        assert _parse_message_link("https://canary.discord.com/channels/1/2/3") == (
            1,
            2,
            3,
        )

    def test_discordapp_domain(self):
        assert _parse_message_link("https://discordapp.com/channels/1/2/3") == (1, 2, 3)

    def test_link_inside_sentence_is_ignored(self):
        assert _parse_message_link(f"check this out {LINK}") is None

    def test_channel_link_is_ignored(self):
        assert _parse_message_link("https://discord.com/channels/111/222") is None

    def test_plain_text_is_ignored(self):
        assert _parse_message_link("hello world") is None

    def test_empty_content(self):
        assert _parse_message_link("") is None


class TestStripMentions:
    def test_user_mention_removed(self):
        assert _strip_mentions("hey <@123456> welcome") == "hey welcome"

    def test_nickname_mention_removed(self):
        assert _strip_mentions("hey <@!123456> welcome") == "hey welcome"

    def test_role_mention_removed(self):
        assert _strip_mentions("attention <@&987654> members") == "attention members"

    def test_multiple_mentions_removed(self):
        assert _strip_mentions("<@1> <@!2> <@&3> done") == "done"

    def test_text_without_mentions_unchanged(self):
        assert _strip_mentions("no mentions here") == "no mentions here"

    def test_newlines_preserved(self):
        assert _strip_mentions("line one <@1>\nline two") == "line one\nline two"

    def test_channel_mention_kept(self):
        # Channel mentions don't ping anyone, so they stay
        assert _strip_mentions("see <#555>") == "see <#555>"
