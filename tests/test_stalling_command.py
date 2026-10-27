from app.agent.v2.tools import _stalling_command as stalls


def test_refuses_the_commands_that_hung_jobs():
    assert stalls('grep -ril 銀行 ~/.dan/workspace')
    assert stalls('find /Users/mikihonda/done -name x')
    assert stalls("osascript -e 'tell application \"System Events\" to keystroke \"a\"'")


def test_lets_narrow_searches_run():
    assert not stalls('rg -n 銀行 ~/.dan/workspace/memory --type md')
    assert not stalls('grep -n x notes.txt')
    assert not stalls('osascript -e "set volume output volume 50"')
    assert not stalls('ls ~ | grep -i done')
