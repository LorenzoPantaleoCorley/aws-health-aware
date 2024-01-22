delete:
	aws cloudformation delete-stack --stack-name cfn-aha-e0 --region eu-central-1 --profile []

build:
	sam build -cu

deploy: 
	if [ -z $(profile) ]; then \
		sam deploy --stack-name cfn-aha-e0 --resolve-s3 --template template.yaml --no-fail-on-empty-changeset --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND ; \
		# sam deploy --stack-name cfn-aha-e0 --template template.yaml --no-fail-on-empty-changeset --config-env $(env) --parameter-overrides $$(sed -e '/^#/d' ../.params/$(env)/params.env) --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND ; \
	else \
		sam deploy --stack-name cfn-aha-e0 --resolve-s3 --template template.yaml --confirm-changeset --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND --profile $(profile); \
		# sam deploy --stack-name cfn-aha-e0 --template template.yaml --confirm-changeset --config-env $(env) --parameter-overrides $$(sed -e '/^#/d' ../.params/$(env)/params.env) --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND --profile $(profile); \
	fi