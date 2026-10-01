# ACUVUE Singapore Brand Colors

Source: https://www.acuvue.com/en-sg/ (extracted from the site's CSS, ranked by usage count)

| Role | Hex | Uses | Notes |
|---|---|---|---|
| Primary teal | `#178197` | 65 | Main brand and accent color |
| Dark teal | `#0A5F72` | 35 | Hover states and headers |
| Bright blue | `#0A7CC1` | 37 | Links and buttons |
| Magenta/purple | `#A51890` | 22 | Highlight and CTA accent |
| Navy | `#051F4A` | 12 | Dark backgrounds and headings |
| Deep navy | `#040B40` | 2 | Darkest background |
| Light blue | `#59A5D7` | 2 | Secondary accent |
| Text black | `#191919` | 17 | Body text |
| Grey text | `#555555` | 4 | Secondary text |
| Mid grey | `#999999` | 20 | Muted text and borders |
| Light grey | `#CCCCCC` | 8 | Dividers |
| Off-white | `#F8F8F8` | 3 | Section backgrounds |
| White | `#FFFFFF` | 114 | Page background |
| Error red | `#DD1C14` | 2 | Errors |
| Success green | `#168012` | 1 | Success |

`#007AFF` also appears but comes from the Swiper carousel library default, so it is excluded.

## Streamlit theme (`.streamlit/config.toml`)

```toml
[theme]
primaryColor = "#178197"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8F8F8"
textColor = "#191919"
```

## Chart series order

`#178197`, `#0A7CC1`, `#A51890`, `#051F4A`, `#59A5D7`
