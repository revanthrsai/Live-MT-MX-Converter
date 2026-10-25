# Bundled sample messages

These examples are synthetic fixtures for development and learning. They are not real customer payment instructions and must not be used for production banking.

| Source format | Sample file | Notes |
| --- | --- | --- |
| `pacs.008` | `pacs.008.xml` | FI-to-FI customer credit transfer |
| `pacs.004` | `pacs.004.xml` | Payment return |
| `pacs.002` | `pacs.002.xml` | Payment status report |
| `pain.001` | `pain.001.xml` | Customer credit transfer initiation |
| `pain.002` | `pain.002.xml` | Customer payment status report |
| `pain.008` | `pain.008.xml` | Customer direct debit initiation |
| `camt.053` | `camt.053.xml` | Bank-to-customer statement |
| `camt.054` | `camt.054.xml` | Debit/credit notification |
| `camt.056` | `camt.056.xml` | Payment cancellation request |
| `MT103` | `MT103.txt` | Customer credit transfer |
| `MT103 RETN` | `MT103-RETN.txt` | Returned customer transfer |
| `MT101` | `MT101.txt` | Request for transfer |
| `MT104` | `MT104.txt` | Direct debit / debit transfer request |
| `MT940` | `MT940.txt` | Customer statement |
| `MT900 / MT910` | `MT910.txt` | Credit confirmation sample; actual output type is determined by debit/credit data |
| `MT192` | `MT192.txt` | Request for cancellation |

`MT199.txt` is also included as a reference fixture, but MT199 is currently a destination-only format in this engine and is not offered as a source conversion.
