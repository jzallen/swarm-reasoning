# Cloudflare Configuration

Cloudflare (free tier) provides edge proxy, DDoS protection, SSL termination,
and rate limiting for the swarm-reasoning application.

## Prerequisites

1. A Cloudflare account (free tier is sufficient)
2. A registered domain with nameservers pointed to Cloudflare
3. The AWS infrastructure stack deployed (for ALB and CloudFront DNS names)

## Setup Steps

### 1. Add Domain to Cloudflare

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Add your domain and select the Free plan
3. Update your domain registrar's nameservers to Cloudflare's assigned nameservers

### 2. Configure SSL/TLS

Settings from `ssl-settings.json`:

1. **SSL/TLS > Overview**: Set encryption mode to **Full (strict)**
2. **SSL/TLS > Edge Certificates**:
   - Minimum TLS Version: **TLS 1.2**
   - Enable **HSTS** with max-age 31536000 and includeSubDomains

### 3. Create DNS Records

Records from `dns-records.json`:

| Type  | Name | Content                         | Proxy |
|-------|------|---------------------------------|-------|
| CNAME | api  | `<ALB DNS name from CloudFormation>` | On    |
| CNAME | @    | `<CloudFront distribution domain>`   | On    |

Replace placeholder values with actual outputs from the CloudFormation stack.

### 4. Configure Rate Limiting

Rule from `rate-limit-rules.json`:

1. **Security > WAF > Rate limiting rules**
2. Create rule:
   - **Expression**: `POST` requests to `/sessions/*/claims`
   - **Rate**: 10 requests per 60 seconds per IP
   - **Action**: Block with 429 response
   - **Timeout**: 60 seconds

### 5. Configure Cache Rules

Rules from `cache-rules.json`:

1. **Caching > Cache Rules**
2. Rule 1: Cache `/assets/*` (static frontend files)
3. Rule 2: Bypass cache for `/sessions/*` and `/health` (API endpoints)
4. Rule 3: Bypass cache for SSE stream endpoints

## Verification

After setup, verify:

```bash
# SSL is working (Full Strict)
curl -I https://api.yourdomain.com/health

# Rate limiting is active (11th request should return 429)
for i in $(seq 1 11); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    https://api.yourdomain.com/sessions/test/claims \
    -H "Content-Type: application/json" \
    -d '{"text":"test"}'
done

# Static assets are cached (check cf-cache-status header)
curl -I https://yourdomain.com/assets/main.js
```

## Free Tier Limits

- 1 rate limiting rule (we use it for claim submission)
- 3 page rules
- Basic DDoS protection (always on)
- Universal SSL certificate
