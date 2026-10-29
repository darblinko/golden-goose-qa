# One-origin ALB. The web app is the default target; a path rule sends /api/*
# to the API, which serves under that prefix (GG_API_ROOT_PATH=/api, see
# services.tf). The browser therefore talks to a single origin — no cross-origin
# CORS split and no API URL baked into the web bundle.
#
# TLS is opt-in: set var.acm_certificate_arn to add a 443 listener and redirect
# 80 -> 443. Without it the ALB serves plain HTTP, acceptable only for a closed
# disposable test deploy.

locals {
  tls_enabled = var.acm_certificate_arn != ""
}

resource "aws_lb" "main" {
  name               = local.name
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name}-web"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path = "/"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    # Matches GG_API_ROOT_PATH=/api — the API serves health under the prefix.
    path = "/api/health"
  }
}

# Port 80: forwards to web directly when there is no certificate, or redirects
# to 443 when there is. Exactly one of these is created.
resource "aws_lb_listener" "http_forward" {
  count             = local.tls_enabled ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  count             = local.tls_enabled ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = local.tls_enabled ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

locals {
  # Splat + one() so the non-selected branch yields null instead of indexing a
  # count=0 resource (which would fault at plan time when TLS toggles).
  primary_listener_arn = (
    local.tls_enabled
    ? one(aws_lb_listener.https[*].arn)
    : one(aws_lb_listener.http_forward[*].arn)
  )
}

# /api/* to the API on whichever listener actually serves traffic.
resource "aws_lb_listener_rule" "api" {
  listener_arn = local.primary_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}
