"""What no published day file may hold, and error text fit for one: shared by the three Daily producers (d7_daily, d8_ok_daily, d9_nm_daily).

Their --check runs in the nightly before anything is committed or published, so a night whose output breaks a rule is dropped, not
published. An independent review found that the Texas and Oklahoma checks looked at no text at all and the New Mexico one only for an
address (the two reports that once named a sole proprietor reached the live site that way, and the nightly's commit starts no CI, so
the tests never saw it). Standard library only.
"""
import html
import re

PHONE = re.compile(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")


def scan(text, digits=False):
    """What a published file's text holds that it must not: an e-mail address, a web address, a phone number and, with `digits` (Oklahoma and
    New Mexico publish no API numbers), a run of 10 or more digits. Returns short descriptions; [] when clean."""
    out = []
    if "@" in text:
        out.append("an e-mail address")
    if re.search(r"https?://", text):
        out.append("a web address")
    if PHONE.search(text):
        out.append("a phone number")
    if digits and re.search(r"\d{10,}", text):
        out.append("a run of 10 or more digits (an API number?)")
    return out


def mask(text):
    """The shape of a value (letters become A, digits 9) for a log line about a name the rules refuse: the log must not republish it."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", str(text)))[:60]


def clean_error(e, n=160):
    """An error as one short line for a report: no web address, no server markup, no path on the machine that ran it. The data files
    and the page never carry them; the log has the whole text."""
    text = html.unescape(str(e))
    # a server's error page: its HTML tags only (a Python exception's own <urlopen error ...> is the reason, and stays)
    text = re.sub(r"</?(?:html|head|title|body|h[1-6]|p|br|hr|div|span|a|b|i|u|em|strong|center|font|table|tr|td|th|ul|ol|li|pre|meta|link|script|style|form|input|img)\b[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"https?://[^\s\"'<>)\]]+", "<address>", text)
    text = re.sub(r"(?<![\w<])/(?:[\w.-]+/)+[\w.-]*", "<path>", text)  # /home/runner/work/...
    return " ".join(text.split())[:n]
