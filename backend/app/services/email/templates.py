"""HTML email templates for CarFINDa agent notifications."""


def _base_wrapper(content: str) -> str:
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F6F4F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F6F4F0;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#FDFCFA;border-radius:12px;border:1px solid #E5E0D8;overflow:hidden;">
<!-- Header -->
<tr><td style="background:#1C1916;padding:20px 28px;">
  <span style="font-family:Georgia,serif;font-style:italic;color:#FDFCFA;font-size:20px;">CarFINDa</span>
  <span style="color:#7A7267;font-size:12px;float:right;line-height:28px;">Your car agent</span>
</td></tr>
<!-- Body -->
<tr><td style="padding:28px;">
{content}
</td></tr>
<!-- Footer -->
<tr><td style="padding:16px 28px;border-top:1px solid #E5E0D8;">
  <p style="margin:0;font-size:11px;color:#7A7267;line-height:1.5;">
    You received this because you subscribed to CarFINDa alerts.
    Reply to this email to take action or unsubscribe.
  </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def negotiation_update_email(
    car_title: str,
    car_price: str,
    seller_reply: str,
    suggested_response: str,
    fair_price_range: str,
    image_url: str = "",
) -> tuple[str, str]:
    """Build a negotiation update email. Returns (subject, html)."""
    subject = f"Seller replied about {car_title}"

    image_block = ""
    if image_url:
        image_block = f'<img src="{image_url}" alt="{car_title}" style="width:100%;height:180px;object-fit:cover;border-radius:8px;margin-bottom:16px;" />'

    content = f"""\
{image_block}
<h2 style="margin:0 0 4px;font-size:18px;color:#1C1916;font-family:Georgia,serif;font-style:italic;">
  A seller replied
</h2>
<p style="margin:0 0 20px;font-size:13px;color:#7A7267;">{car_title} &middot; {car_price}</p>

<div style="background:#F6F4F0;border-radius:8px;padding:16px;margin-bottom:20px;">
  <p style="margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#7A7267;font-weight:600;">Seller says</p>
  <p style="margin:0;font-size:14px;color:#1C1916;line-height:1.5;">&ldquo;{seller_reply}&rdquo;</p>
</div>

<div style="background:#f0fdf4;border-left:3px solid #22c55e;border-radius:0 8px 8px 0;padding:16px;margin-bottom:20px;">
  <p style="margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#15803d;font-weight:600;">Our recommended reply</p>
  <p style="margin:0;font-size:14px;color:#1C1916;line-height:1.5;">&ldquo;{suggested_response}&rdquo;</p>
</div>

<p style="margin:0 0 20px;font-size:12px;color:#7A7267;">
  Fair market range: <strong style="color:#1C1916;">{fair_price_range}</strong>
</p>

<p style="margin:0;font-size:13px;color:#7A7267;">
  Reply to this email with <strong style="color:#1C1916;">&ldquo;send&rdquo;</strong> to send our suggested response,
  or write your own reply and we&rsquo;ll forward it.
</p>"""

    return subject, _base_wrapper(content)


def outreach_summary_email(
    search_query: str,
    messages_sent: int,
    listings: list[dict],
) -> tuple[str, str]:
    """Build an outreach summary email. Returns (subject, html)."""
    subject = f"CarFINDa sent {messages_sent} negotiation messages for you"

    listing_rows = ""
    for l in listings[:5]:
        title = l.get("title", f"{l.get('year', '')} {l.get('make', '')} {l.get('model', '')}".strip())
        price = l.get("price", 0)
        price_str = f"${price:,.0f}" if price else "N/A"
        target = l.get("target_price")
        target_str = f" &rarr; Target: ${target:,.0f}" if target else ""
        status = l.get("status", "sent")
        badge_color = "#22c55e" if status == "sent" else "#EAB308"
        listing_rows += f"""\
<tr>
  <td style="padding:8px 0;border-bottom:1px solid #E5E0D8;">
    <p style="margin:0;font-size:13px;color:#1C1916;font-weight:500;">{title}</p>
    <p style="margin:2px 0 0;font-size:12px;color:#7A7267;">{price_str}{target_str}</p>
  </td>
  <td style="padding:8px 0;border-bottom:1px solid #E5E0D8;text-align:right;">
    <span style="font-size:10px;font-weight:600;color:{badge_color};text-transform:uppercase;">{status}</span>
  </td>
</tr>"""

    content = f"""\
<h2 style="margin:0 0 4px;font-size:18px;color:#1C1916;font-family:Georgia,serif;font-style:italic;">
  Outreach complete
</h2>
<p style="margin:0 0 20px;font-size:13px;color:#7A7267;">
  Your agent sent <strong style="color:#1C1916;">{messages_sent}</strong> negotiation messages
  for &ldquo;{search_query}&rdquo;
</p>

<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
{listing_rows}
</table>

<p style="margin:0;font-size:13px;color:#7A7267;">
  We&rsquo;ll email you when sellers reply with our suggested counter-offers.
</p>"""

    return subject, _base_wrapper(content)


def price_drop_email(
    car_title: str,
    old_price: float,
    new_price: float,
    drop_amount: float,
    drop_pct: float,
    market_avg: float | None = None,
    image_url: str = "",
    listing_url: str = "",
) -> tuple[str, str]:
    """Build a price drop alert email. Returns (subject, html)."""
    subject = f"Price dropped ${drop_amount:,.0f} on {car_title}"

    image_block = ""
    if image_url:
        image_block = f'<img src="{image_url}" alt="{car_title}" style="width:100%;height:180px;object-fit:cover;border-radius:8px;margin-bottom:16px;" />'

    market_line = ""
    if market_avg and new_price < market_avg:
        below_pct = round((1 - new_price / market_avg) * 100)
        market_line = f'<p style="margin:0 0 8px;font-size:12px;color:#15803d;font-weight:500;">Now {below_pct}% below market average (${market_avg:,.0f})</p>'

    link_block = ""
    if listing_url:
        link_block = f'<a href="{listing_url}" style="display:inline-block;background:#1C1916;color:#FDFCFA;font-size:13px;font-weight:500;padding:10px 20px;border-radius:9999px;text-decoration:none;margin-top:16px;">View listing &rarr;</a>'

    content = f"""\
{image_block}
<h2 style="margin:0 0 4px;font-size:18px;color:#1C1916;font-family:Georgia,serif;font-style:italic;">
  Price dropped
</h2>
<p style="margin:0 0 16px;font-size:13px;color:#7A7267;">{car_title}</p>

<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;">
<tr>
  <td style="text-align:center;padding:16px;background:#F6F4F0;border-radius:8px 0 0 8px;">
    <p style="margin:0;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#7A7267;font-weight:600;">Was</p>
    <p style="margin:4px 0 0;font-size:20px;color:#7A7267;text-decoration:line-through;">${old_price:,.0f}</p>
  </td>
  <td style="text-align:center;padding:16px;font-size:20px;color:#7A7267;">&rarr;</td>
  <td style="text-align:center;padding:16px;background:#f0fdf4;border-radius:0 8px 8px 0;">
    <p style="margin:0;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#15803d;font-weight:600;">Now</p>
    <p style="margin:4px 0 0;font-size:20px;color:#15803d;font-weight:700;">${new_price:,.0f}</p>
  </td>
</tr>
</table>

<p style="margin:0 0 4px;font-size:14px;color:#1C1916;font-weight:600;">
  Dropped ${drop_amount:,.0f} ({drop_pct:.0f}%)
</p>
{market_line}

{link_block}"""

    return subject, _base_wrapper(content)


def new_matches_email(
    search_query: str,
    matches: list[dict],
) -> tuple[str, str]:
    """Build a new matches alert email. Returns (subject, html)."""
    count = len(matches)
    subject = f"{count} new listing{'s' if count != 1 else ''} matching \"{search_query}\""

    listing_rows = ""
    for m in matches[:5]:
        title = m.get("title", f"{m.get('year', '')} {m.get('make', '')} {m.get('model', '')}".strip())
        price = m.get("price", 0)
        price_str = f"${price:,.0f}" if price else ""
        score = m.get("score", 0)
        score_color = "#22c55e" if score >= 80 else "#EAB308" if score >= 60 else "#F97316" if score >= 40 else "#EF4444"
        listing_rows += f"""\
<tr>
  <td style="padding:10px 0;border-bottom:1px solid #E5E0D8;">
    <p style="margin:0;font-size:13px;color:#1C1916;font-weight:500;">{title}</p>
    <p style="margin:2px 0 0;font-size:12px;color:#7A7267;">{price_str}</p>
  </td>
  <td style="padding:10px 0;border-bottom:1px solid #E5E0D8;text-align:right;">
    <span style="display:inline-block;width:28px;height:28px;border-radius:50%;background:{score_color};color:white;font-size:11px;font-weight:700;line-height:28px;text-align:center;">{score}</span>
  </td>
</tr>"""

    remaining = count - 5
    more_line = f'<p style="margin:12px 0 0;font-size:12px;color:#7A7267;">+ {remaining} more</p>' if remaining > 0 else ""

    content = f"""\
<h2 style="margin:0 0 4px;font-size:18px;color:#1C1916;font-family:Georgia,serif;font-style:italic;">
  New matches found
</h2>
<p style="margin:0 0 20px;font-size:13px;color:#7A7267;">
  {count} new listing{'s' if count != 1 else ''} for &ldquo;{search_query}&rdquo;
</p>

<table width="100%" cellpadding="0" cellspacing="0">
{listing_rows}
</table>
{more_line}"""

    return subject, _base_wrapper(content)
