<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import AdminSettingField from './AdminSettingField.svelte';
	import AdminSettingRow from './AdminSettingRow.svelte';
	import { getMcpKeyDbConfig, setMcpKeyDbConfig, testMcpKeyDbConfig } from '$lib/apis/configs';

	const i18n = getContext<Writable<i18nType>>('i18n');

	const inputClass =
		'w-full h-7 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';
	const textareaClass =
		'w-full rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 py-1.5 font-mono text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';
	const buttonClass =
		'flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-normal transition disabled:opacity-60 disabled:cursor-not-allowed';

	type McpKeyDbConfig = {
		ENABLE: boolean;
		HOST: string;
		PORT: number;
		DATABASE: string;
		USERNAME: string;
		PASSWORD: string;
		PASSWORD_SET?: boolean;
		QUERY: string;
		CACHE_TTL: number;
		TIMEOUT: number;
		CONNECTION_STRING: string;
		ENABLE_CONNECTION_STRING: boolean;
	};

	let config: McpKeyDbConfig | null = null;
	let testEmail = '';
	let testResult: { email: string; servers: string[]; ignored_options?: string[] } | null = null;

	// The Connection Settings drawer starts closed and opens when the feature is turned on.
	let showSettings = false;

	const toggleEnable = () => {
		if (config?.ENABLE) showSettings = true;
	};

	$: usingConnectionString = !!config?.ENABLE_CONNECTION_STRING;
	let saving = false;
	let testing = false;

	// The saved password is never sent to the browser; an empty field keeps it.
	const payload = () => ({
		...config,
		PASSWORD: config?.PASSWORD || null,
		PORT: Number(config?.PORT) || 1433,
		CACHE_TTL: Number(config?.CACHE_TTL) || 0,
		TIMEOUT: Number(config?.TIMEOUT) || 10
	});

	const load = async (data: Omit<McpKeyDbConfig, 'PASSWORD'>) => {
		config = { ...data, PASSWORD: '' };
	};

	const saveHandler = async () => {
		if (!config) return;
		saving = true;
		const res = await setMcpKeyDbConfig(localStorage.token, payload()).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			await load(res);
			toast.success($i18n.t('MCP key database settings saved'));
		}
		saving = false;
	};

	const testHandler = async () => {
		if (!config) return;
		testing = true;
		testResult = null;
		const res = await testMcpKeyDbConfig(localStorage.token, {
			...payload(),
			EMAIL: testEmail.trim() || null
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			testResult = res;
			toast.success($i18n.t('Connected to the MCP key database'));
		}
		testing = false;
	};

	onMount(async () => {
		const res = await getMcpKeyDbConfig(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			await load(res);
		}
	});
</script>

{#if config}
	<div class="flex flex-col gap-3">
		<AdminSettingRow
			label={$i18n.t('Enable MCP Key Database')}
			description={$i18n.t(
				'MCP connections using the "Key Database" auth type, or {{placeholder}} in a header, look up each user\'s API key here by email. Users only see a connection when the query returns a row whose variable matches its Access Variable.',
				{ placeholder: '{{MCP_KEY}}' }
			)}
			let:labelId
		>
			<Switch bind:state={config.ENABLE} on:change={toggleEnable} ariaLabelledbyId={labelId} />
		</AdminSettingRow>

		<button
			type="button"
			class="flex items-center gap-1 self-start text-xs text-gray-600 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
			aria-expanded={showSettings}
			aria-controls="mcp-key-db-settings-panel"
			on:click={() => (showSettings = !showSettings)}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 20 20"
				fill="currentColor"
				class="h-3 w-3 transition-transform {showSettings ? 'rotate-90' : ''}"
				aria-hidden="true"
			>
				<path
					fill-rule="evenodd"
					d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
					clip-rule="evenodd"
				/>
			</svg>
			{$i18n.t('Connection Settings')}
		</button>

		{#if showSettings}
			<div id="mcp-key-db-settings-panel" class="flex flex-col gap-3">
				<div class="flex flex-col gap-1">
					<div class="flex items-center justify-between gap-4">
						<label
							id="mcp-key-db-connection-string-label"
							for="mcp-key-db-connection-string"
							class="text-xs text-gray-600 dark:text-gray-400">{$i18n.t('Connection String')}</label
						>

						<Switch
							bind:state={config.ENABLE_CONNECTION_STRING}
							ariaLabelledbyId="mcp-key-db-connection-string-label"
						/>
					</div>

					<AdminSettingField
						description={config.ENABLE_CONNECTION_STRING
							? $i18n.t(
									'In use instead of the host, port, database, username and password below. The saved password shows as ******** — leave it to keep it.'
								)
							: $i18n.t(
									'Off: the host, port, database, username and password below are used. Turn it on to use this string instead.'
								)}
					>
						<SensitiveInput
							id="mcp-key-db-connection-string"
							variant="settings"
							bind:value={config.CONNECTION_STRING}
							placeholder="Server=sqlserver.example.local,1433;Database=...;User Id=...;Password=...;"
							required={false}
						/>
					</AdminSettingField>
				</div>

				<fieldset
					class="flex min-w-0 flex-col gap-3 disabled:opacity-50"
					disabled={usingConnectionString}
				>
					<div class="flex gap-2">
						<AdminSettingField className="flex-1" label={$i18n.t('Host')} forId="mcp-key-db-host">
							<input
								id="mcp-key-db-host"
								class={inputClass}
								type="text"
								bind:value={config.HOST}
								placeholder="sqlserver.example.local"
								autocomplete="off"
							/>
						</AdminSettingField>

						<AdminSettingField className="w-24" label={$i18n.t('Port')} forId="mcp-key-db-port">
							<input
								id="mcp-key-db-port"
								class={inputClass}
								type="number"
								min="1"
								max="65535"
								bind:value={config.PORT}
								placeholder="1433"
							/>
						</AdminSettingField>
					</div>

					<AdminSettingField label={$i18n.t('Database')} forId="mcp-key-db-database">
						<input
							id="mcp-key-db-database"
							class={inputClass}
							type="text"
							bind:value={config.DATABASE}
							placeholder={$i18n.t('Database name')}
							autocomplete="off"
						/>
					</AdminSettingField>

					<div class="flex gap-2">
						<AdminSettingField
							className="flex-1"
							label={$i18n.t('Username')}
							description={$i18n.t('SQL login, or DOMAIN\\user for a Windows account')}
							forId="mcp-key-db-username"
						>
							<input
								id="mcp-key-db-username"
								class={inputClass}
								type="text"
								bind:value={config.USERNAME}
								autocomplete="off"
							/>
						</AdminSettingField>

						<AdminSettingField
							className="flex-1"
							label={$i18n.t('Password')}
							description={config.PASSWORD_SET
								? $i18n.t('Saved. Leave blank to keep it.')
								: $i18n.t('Not set')}
						>
							<SensitiveInput
								variant="settings"
								bind:value={config.PASSWORD}
								placeholder={config.PASSWORD_SET ? '••••••••' : ''}
								required={false}
							/>
						</AdminSettingField>
					</div>
				</fieldset>

				<AdminSettingField
					label={$i18n.t('Query')}
					description={$i18n.t(
						"Return one row for each MCP connection the user may use, with two columns: variable, which matches the connection's Access Variable (for example hr), and key, the API key sent to that server. @email is replaced with the signed-in user's email. In SQL Server, write the column as [key], since key is a reserved word."
					)}
					forId="mcp-key-db-query"
				>
					<textarea
						id="mcp-key-db-query"
						class={textareaClass}
						rows="6"
						spellcheck="false"
						bind:value={config.QUERY}
					></textarea>
				</AdminSettingField>

				<div class="flex gap-2">
					<AdminSettingField
						className="flex-1"
						label={$i18n.t('Cache (seconds)')}
						description={$i18n.t(
							"How long a user's keys are reused before the database is queried again"
						)}
						forId="mcp-key-db-cache-ttl"
					>
						<input
							id="mcp-key-db-cache-ttl"
							class={inputClass}
							type="number"
							min="0"
							bind:value={config.CACHE_TTL}
						/>
					</AdminSettingField>

					<AdminSettingField
						className="flex-1"
						label={$i18n.t('Timeout (seconds)')}
						forId="mcp-key-db-timeout"
					>
						<input
							id="mcp-key-db-timeout"
							class={inputClass}
							type="number"
							min="1"
							max="60"
							bind:value={config.TIMEOUT}
						/>
					</AdminSettingField>
				</div>

				<AdminSettingField
					label={$i18n.t('Test Email')}
					description={$i18n.t(
						'Runs the query for this email (yours if blank). Keys are never shown.'
					)}
					forId="mcp-key-db-test-email"
				>
					<div class="flex gap-2">
						<input
							id="mcp-key-db-test-email"
							class={inputClass}
							type="email"
							bind:value={testEmail}
							placeholder={$i18n.t('user@example.com')}
							autocomplete="off"
						/>
						<button
							class="{buttonClass} border border-gray-100 text-gray-700 hover:bg-gray-50 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-850"
							type="button"
							disabled={testing}
							on:click={testHandler}
						>
							{$i18n.t('Test')}
							{#if testing}<Spinner className="size-3" />{/if}
						</button>
					</div>
				</AdminSettingField>

				{#if testResult}
					<div class="text-[0.6875rem] text-gray-500">
						{#if testResult.servers.length}
							{$i18n.t('{{email}} has keys for variables:', { email: testResult.email })}
							<span class="font-mono text-gray-700 dark:text-gray-300"
								>{testResult.servers.join(', ')}</span
							>
						{:else}
							{$i18n.t('Connected, but no active keys were found for {{email}}.', {
								email: testResult.email
							})}
						{/if}
						{#if testResult.ignored_options?.length}
							<div class="mt-0.5">
								{$i18n.t('Connection string options not used:')}
								<span class="font-mono">{testResult.ignored_options.join(', ')}</span>
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex justify-end">
			<button
				class="{buttonClass} bg-gray-900 text-white hover:bg-black dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
				type="button"
				disabled={saving}
				on:click={saveHandler}
			>
				{$i18n.t('Save')}
				{#if saving}<Spinner className="size-3" />{/if}
			</button>
		</div>
	</div>
{:else}
	<div class="py-2">
		<Spinner />
	</div>
{/if}
