.PHONY: build deploy deploy-all deploy-agentcore deploy-lambda bootstrap clean secret-update destroy help configure studio-deploy preflight capture-rules

# Load environment variables from .env file
-include .env

# Load local customizations if present (gitignored; personal testing targets)
-include Makefile.local

# Unset AWS_PROFILE from shell environment to force reading from .env only
unexport AWS_PROFILE
AWS_PROFILE := $(shell grep '^AWS_PROFILE=' .env 2>/dev/null | cut -d '=' -f 2-)

# Repository root, for running python modules through the project's uv env
REPO_ROOT := $(shell cd ../.. && pwd)
WIZARD_PORT ?= 8787

# Default target
help:
	@echo "TAC AgentCore + Lambda Deployment"
	@echo ""
	@echo "Available targets:"
	@echo "  configure        - Launch the local IVR configuration wizard"
	@echo "  bootstrap        - Bootstrap CDK (one-time setup)"
	@echo "  build            - Build agent code and CDK"
	@echo "  preflight        - Verify Conversation Orchestrator capture rules"
	@echo "  capture-rules    - Add the Orchestrator capture rules the IVR needs"
	@echo "  studio-deploy    - Publish the Studio flow and wire the phone number"
	@echo "  deploy           - Build, deploy all stacks, then publish the Studio flow"
	@echo "  deploy-all       - Build and deploy all stacks (Secrets, AgentCore, Lambda)"
	@echo "  deploy-agentcore - Build and deploy only AgentCore stack"
	@echo "  deploy-lambda    - Build and deploy only Lambda stack"
	@echo "  secret-update    - Update Secrets Manager with credentials from .env"
	@echo "  destroy          - Destroy all stacks and clean up Studio flow"
	@echo "  clean            - Clean build artifacts"
	@echo ""
	@echo "Usage:"
	@echo "  make configure   # Set up your IVR configuration (first-time setup)"
	@echo "  make bootstrap   # One-time CDK setup"
	@echo "  make deploy      # Build, deploy, and publish the Studio flow"
	@echo "  make destroy     # Delete all AWS resources and Studio flow"

# Launch the local configuration wizard
configure:
	@echo "Starting the IVR configuration wizard on http://127.0.0.1:$(WIZARD_PORT)"
	@echo "Press Ctrl-C when you are done."
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda \
		uv run uvicorn wizard.server:default_app \
			--factory --host 127.0.0.1 --port $(WIZARD_PORT)

# Verify Conversation Orchestrator is capturing traffic for the IVR number
preflight:
ifndef TWILIO_API_KEY
	$(error TWILIO_API_KEY is not set. Run 'make configure' first)
endif
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda \
		TWILIO_ACCOUNT_SID="$(TWILIO_ACCOUNT_SID)" \
		TWILIO_AUTH_TOKEN="$(TWILIO_AUTH_TOKEN)" \
		TWILIO_API_KEY="$(TWILIO_API_KEY)" \
		TWILIO_API_SECRET="$(TWILIO_API_SECRET)" \
		uv run python -m studio.preflight

# Add the Orchestrator capture rules the IVR needs (best effort)
capture-rules:
ifndef TWILIO_API_KEY
	$(error TWILIO_API_KEY is not set. Run 'make configure' first)
endif
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda \
		TWILIO_API_KEY="$(TWILIO_API_KEY)" \
		TWILIO_API_SECRET="$(TWILIO_API_SECRET)" \
		uv run python -m studio.capture_rules

# Publish the Studio flow and point the phone number at it
studio-deploy:
ifndef TWILIO_API_KEY
	$(error TWILIO_API_KEY is not set. Run 'make configure' first)
endif
ifndef IVR_SESSION_TOKEN
	$(error IVR_SESSION_TOKEN is not set. Run 'make configure' first)
endif
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda \
		AWS_PROFILE="$(AWS_PROFILE)" \
		TWILIO_ACCOUNT_SID="$(TWILIO_ACCOUNT_SID)" \
		TWILIO_AUTH_TOKEN="$(TWILIO_AUTH_TOKEN)" \
		TWILIO_API_KEY="$(TWILIO_API_KEY)" \
		TWILIO_API_SECRET="$(TWILIO_API_SECRET)" \
		IVR_SESSION_TOKEN="$(IVR_SESSION_TOKEN)" \
		uv run python -m studio.provision

# Bootstrap CDK (one-time setup)
bootstrap:
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
ifndef AWS_ACCOUNT_ID
	$(error AWS_ACCOUNT_ID is not set in .env file)
endif
ifndef AWS_REGION
	$(error AWS_REGION is not set in .env file)
endif
	@echo "Installing CDK dependencies..."
	cd cdk && npm ci
	@echo ""
	@echo "Building CDK TypeScript..."
	cd cdk && npm run build
	@echo ""
	@echo "Bootstrapping CDK..."
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx cdk bootstrap \
		aws://$(AWS_ACCOUNT_ID)/$(AWS_REGION)
	@echo ""
	@echo "✓ CDK bootstrapped for $(AWS_ACCOUNT_ID) in $(AWS_REGION)"

# Build everything
build:
	@echo "Building Python agent..."
	cd agent && uv sync --frozen
	@echo ""
	@echo "Copying ivr-config.json into the agent bundle..."
	@test -f ivr-config.json || (echo "Missing ivr-config.json. Run 'make configure' first." && exit 1)
	cp ivr-config.json agent/ivr-config.json
	@echo "Generating the extension destination map for the Lambda..."
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda/agent uv run python -c \
		"import json; from ivr_config import load_config; \
print(json.dumps(load_config().extension_destinations()))" \
		> deploy/agentcore_aws_lambda/agent/ivr-extension-destinations.json
	@echo ""
	@echo "Building CDK..."
	cd cdk && npm ci && npm run build

# Update Secrets Manager with credentials from .env (secrets only, not configuration)
secret-update:
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
ifndef TWILIO_ACCOUNT_SID
	$(error TWILIO_ACCOUNT_SID is not set in .env file)
endif
ifndef TWILIO_AUTH_TOKEN
	$(error TWILIO_AUTH_TOKEN is not set in .env file)
endif
ifndef TWILIO_API_KEY
	$(error TWILIO_API_KEY is not set in .env file)
endif
ifndef TWILIO_API_SECRET
	$(error TWILIO_API_SECRET is not set in .env file)
endif
ifndef AWS_REGION
	$(error AWS_REGION is not set in .env file)
endif
	@echo "Updating Secrets Manager with Twilio credentials from .env..."
	@TWILIO_ACCOUNT_SID="$(TWILIO_ACCOUNT_SID)" \
		TWILIO_AUTH_TOKEN="$(TWILIO_AUTH_TOKEN)" \
		TWILIO_API_KEY="$(TWILIO_API_KEY)" \
		TWILIO_API_SECRET="$(TWILIO_API_SECRET)" \
		python3 -c 'import json, os; print(json.dumps({"TWILIO_ACCOUNT_SID": os.environ["TWILIO_ACCOUNT_SID"], "TWILIO_AUTH_TOKEN": os.environ["TWILIO_AUTH_TOKEN"], "TWILIO_API_KEY": os.environ["TWILIO_API_KEY"], "TWILIO_API_SECRET": os.environ["TWILIO_API_SECRET"]}))' | \
		aws secretsmanager put-secret-value \
			--secret-id tac/twilio-credentials \
			--region $(AWS_REGION) \
			--profile $(AWS_PROFILE) \
			--secret-string file:///dev/stdin > /dev/null
	@echo "✓ Secrets updated successfully!"

# Deploy all stacks in stages (Secrets → Update → AgentCore + Lambda)
deploy-all: build
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
	@echo "═══════════════════════════════════════════════════════════"
	@echo "Step 1/3: Deploying Secrets stack..."
	@echo "═══════════════════════════════════════════════════════════"
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx aws-cdk deploy TacSecretsStack --require-approval never
	@echo ""
	@echo "═══════════════════════════════════════════════════════════"
	@echo "Step 2/3: Updating Secrets Manager with credentials from .env..."
	@echo "═══════════════════════════════════════════════════════════"
	@$(MAKE) secret-update
	@echo ""
	@echo "═══════════════════════════════════════════════════════════"
	@echo "Step 3/3: Deploying AgentCore and Lambda stacks..."
	@echo "═══════════════════════════════════════════════════════════"
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx aws-cdk deploy TacAgentCoreStack TacLambdaStack --require-approval never
	@echo ""
	@echo "✓ All stacks deployed!"

# Deploy only AgentCore stack
deploy-agentcore: build
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
	@echo "Deploying AgentCore stack..."
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx aws-cdk deploy TacAgentCoreStack --require-approval never
	@echo ""
	@echo "✓ AgentCore stack deployed!"

# Deploy only Lambda stack
deploy-lambda: build
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
	@echo "Deploying Lambda stack..."
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx aws-cdk deploy TacLambdaStack --require-approval never
	@echo ""
	@echo "✓ Lambda stack deployed!"

# Deploy AWS stacks, then publish the Studio flow and wire the number
deploy: deploy-all studio-deploy
	@echo ""
	@echo "✓ IVR deployed"

# Destroy all stacks (reverse order: Lambda → AgentCore → Secrets)
destroy:
ifndef AWS_PROFILE
	$(error AWS_PROFILE is not set in .env file. Add AWS_PROFILE=<your-profile> to deploy/agentcore_aws_lambda/.env)
endif
	@echo "⚠️  WARNING: This will destroy all stacks and delete all resources!"
	@echo ""
	@echo "Destroying stacks in order: Lambda → AgentCore → Secrets"
	@echo ""
	cd cdk && AWS_PROFILE=$(AWS_PROFILE) npx aws-cdk destroy TacLambdaStack TacAgentCoreStack TacSecretsStack --force
	@echo ""
	@echo "Cleaning up Studio flow and Twilio phone number webhook..."
	cd $(REPO_ROOT) && PYTHONPATH=deploy/agentcore_aws_lambda \
		TWILIO_ACCOUNT_SID="$(TWILIO_ACCOUNT_SID)" \
		TWILIO_AUTH_TOKEN="$(TWILIO_AUTH_TOKEN)" \
		TWILIO_API_KEY="$(TWILIO_API_KEY)" \
		TWILIO_API_SECRET="$(TWILIO_API_SECRET)" \
		uv run python -m studio.teardown
	@echo ""
	@echo "✓ All stacks destroyed!"

# Clean build artifacts
clean:
	rm -rf agent/.venv
	rm -rf agent/__pycache__
	rm -rf lambda/__pycache__
	rm -rf cdk/node_modules
	rm -rf cdk/cdk.out
	rm -rf cdk/dist
	rm -rf cdk/agentcore/.cache
	rm -f agent/ivr-config.json agent/ivr-extension-destinations.json
