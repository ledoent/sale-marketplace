This module flags Amazon merchant-fulfilled (MFN) orders at risk of missing
Amazon's ship-by cutoff:

- Captures the latest/earliest ship date and fulfillment channel from the Orders
  API.
- Computes hours-to-cutoff (wall-clock, or business hours when a working
  calendar is configured on the channel) and a risk state: on track, at risk,
  blocked (delivery not ready to ship), or overdue.

A scheduled action (*Amazon: Update Ship Risk*, disabled by default) recomputes
risk for open MFN orders.
