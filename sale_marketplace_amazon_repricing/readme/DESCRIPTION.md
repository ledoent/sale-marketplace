This module reprices Amazon listings in near-real time from
`ANY_OFFER_CHANGED` notifications delivered to an AWS SQS queue:

- **Subscribe** — register an SQS destination and an `ANY_OFFER_CHANGED`
  subscription via the Notifications API.
- **Drain** — a scheduled action polls the SQS queue, processes each
  notification, and deletes it on success (failed messages are left for
  redelivery). Duplicate redeliveries within a drain are de-duplicated by
  message id.
- **React** — each notification updates the listing's buy-box price, records a
  competitor offer snapshot, and (when price push is enabled) reprices the
  listing using the channel's competitive rule.

Notifications are matched to listings **scoped to the channel**, so the same
ASIN sold through two channels never cross-updates.
