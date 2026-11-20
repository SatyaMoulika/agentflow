const guidance: Record<string, string> = {
  INPUT_MAPPING_FAILED:
    'Check this step’s input mapping and the exact field names in earlier outputs. A referenced field may be missing or have the wrong shape.',
  EXECUTION_FAILED:
    'Check the step configuration and resolved input below. Confirm that required fields, value types and operation limits match the selected step.',
  CONNECTION_UNAVAILABLE:
    'Open Integrations and check that the selected connection is still active. Update the step if the connection was removed or revoked.',
  HTTP_REQUEST_FAILED:
    'Check the connection endpoint and its availability. Inspect recorded HTTP details below before making another request.',
  HTTP_TARGET_BLOCKED:
    'Check that the connection uses an allowed public HTTPS endpoint. Private addresses, redirects and unsupported targets are blocked.',
  PROVIDER_NOT_CONFIGURED:
    'The AI provider is not configured on the server. Ask the person running AgentFlow to configure Groq before starting another run.',
  PROVIDER_AUTH_FAILED:
    'Ask the person running AgentFlow to check the server’s Groq credential. Do not paste API keys into workflow input.',
  PROVIDER_MODEL_UNAVAILABLE:
    'Check the selected model and its availability to the server’s Groq account.',
  PROVIDER_RATE_LIMITED:
    'The provider limited this request. Check the provider details below for retry timing and wait before starting another run.',
  PROVIDER_CONTEXT_LIMIT:
    'Reduce the text or fetched data sent to the model and review the step’s instructions before running again.',
  PROVIDER_OUTPUT_LIMIT:
    'The provider reached an output limit. Ask for a shorter response or review the model settings before running again.',
  PROVIDER_INVALID_RESPONSE:
    'The provider returned a response the step could not use. Review the instructions and recorded provider details.',
  PROVIDER_UNAVAILABLE:
    'The provider could not complete the request. Check its availability and recorded details before starting another run.',
  DEADLINE_EXCEEDED:
    'The execution exceeded a time limit. Inspect completed steps and any external-call records before deciding whether to run again.',
  INTERNAL_FAILURE:
    'AgentFlow could not finish this operation. Inspect the recorded history; if it persists, share the execution ID with the person running AgentFlow.',
};

export function failureGuidance(code: string | null): string {
  return (
    (code && Object.hasOwn(guidance, code) && guidance[code]) ||
    'Inspect the step’s recorded input, configuration and error details below. Share the execution ID with the person running AgentFlow if the cause is unclear.'
  );
}
