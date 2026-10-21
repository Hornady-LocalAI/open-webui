<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { createEventDispatcher } from 'svelte';
	import { onMount, getContext } from 'svelte';

	import { goto } from '$app/navigation';

	import { updateUserById, getUserGroupsById, getUserVariablesById, revokeUserSessions } from '$lib/apis/users';

	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	let showRevokeConfirmation = false;
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	import XMark from '$lib/components/icons/XMark.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import UserProfileImage from '$lib/components/chat/Settings/Account/UserProfileImage.svelte';

	const i18n = getContext<typeof import('$lib/i18n').default>('i18n');
	const dispatch = createEventDispatcher();
	dayjs.extend(localizedFormat);

	export let show = false;
	export let selectedUser;
	export let sessionUser;

	$: if (show) {
		init();
	}

	const init = async () => {
		const loadId = ++variablesLoadId;

		variablesLoaded = false;
		variablesLoadError = '';
		variablesJson = '{}';

		if (!selectedUser) return;

		const userId = selectedUser.id;

		// Work on a copy so unsaved edits don't change the user list.
		_user = { ...selectedUser, password: '' };
		loadUserGroups();

		try {
			const result = await getUserVariablesById(
				localStorage.token,
				userId
			);

			// Ignore a response if the editor has switched users or closed.
			if (
				loadId !== variablesLoadId ||
				!show ||
				selectedUser?.id !== userId
			) return;

			variablesJson = JSON.stringify(result.variables, null, 2);
			variablesLoaded = true;
		} catch (error) {
			if (
				loadId !== variablesLoadId ||
				!show ||
				selectedUser?.id !== userId
			) return;

			variablesLoadError =
				error instanceof Error ? error.message : String(error);
		}
	};

	let _user = {
		profile_image_url: '',
		role: 'pending',
		name: '',
		email: '',
		password: ''
	};
	let variablesJson = '{}';
	let variablesLoaded = false;
	let variablesLoadError = '';
	let variablesLoadId = 0;
	let saving = false;

	let userGroups: any[] | null = null;

	const submitHandler = async () => {
		if (!variablesLoaded || saving) return;

		let variables: Record<string, string>;

		try {
			const parsed: unknown = JSON.parse(variablesJson);

			if (
				parsed === null ||
				typeof parsed !== 'object' ||
				Array.isArray(parsed)
			) {
				throw new Error('Variables must be a JSON object.');
			}

			for (const [key, value] of Object.entries(parsed)) {
				if (!/^[a-z][a-z0-9_]*$/.test(key)) {
					throw new Error(
						`Invalid key "${key}". Use lowercase letters, numbers, and underscores; start with a letter.`
					);
				}

				if (typeof value !== 'string') {
					throw new Error(`The value for "${key}" must be a string.`);
				}
			}

			variables = parsed as Record<string, string>;
		} catch (error) {
			toast.error(
				error instanceof Error ? error.message : 'Invalid variables JSON.'
			);
			return;
		}

		saving = true;

		try {
			const result = await updateUserById(
				localStorage.token,
				selectedUser.id,
				{ ..._user, variables }
			);

			if (result) {
				dispatch('save');
				show = false;
			}
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			saving = false;
		}
	};

	const loadUserGroups = async () => {
		if (!selectedUser?.id) return;
		userGroups = null;

		userGroups = await getUserGroupsById(localStorage.token, selectedUser.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
	};
</script>

<ConfirmDialog
	bind:show={showRevokeConfirmation}
	title={$i18n.t('Sign out all devices?')}
	message={$i18n.t('This user will need to sign in again on every device. API keys remain active.')}
	on:confirm={async () => {
		try {
			await revokeUserSessions(localStorage.token, selectedUser.id);
			toast.success($i18n.t('All sessions revoked'));
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		}
	}}
/>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-4 pt-3 pb-1">
			<div class=" text-sm font-medium self-center">{$i18n.t('Edit User')}</div>
			<button
				class="self-center rounded-lg p-1 text-gray-500 transition hover:bg-gray-50 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-4'} />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<div class=" px-5 pt-3 pb-5 w-full">
						<div class="flex self-center w-full">
							<div class=" self-start h-full mr-6">
								<UserProfileImage
									imageClassName="size-14"
									bind:profileImageUrl={_user.profile_image_url}
									user={_user}
								/>
							</div>

							<div class=" flex-1 min-w-0">
								<div class="overflow-hidden w-ful mb-2">
									<div class=" self-center capitalize font-normal truncate">
										{selectedUser.name}
									</div>

									<div class="text-xs text-gray-500">
										{$i18n.t('Created at')}
										{dayjs(selectedUser.created_at * 1000)
											.locale($i18n.language)
											.format('LL')}
									</div>
								</div>

								<div class=" flex flex-col space-y-1.5">
									{#if (userGroups ?? []).length > 0}
										<div class="flex flex-col w-full text-sm">
											<div class="mb-1 text-xs text-gray-500">{$i18n.t('User Groups')}</div>

											<div class="flex flex-wrap gap-1 my-0.5 -mx-1">
												{#each userGroups as userGroup}
													<span
														class="px-1.5 py-0.5 rounded-xl bg-gray-100 dark:bg-gray-850 text-xs"
													>
														<a
															href={'/admin/users/groups?id=' + userGroup.id}
															on:click|preventDefault={() =>
																goto('/admin/users/groups?id=' + userGroup.id)}
														>
															{userGroup.name}
														</a>
													</span>
												{/each}
											</div>
										</div>
									{/if}

									<div class="flex flex-col w-full">
										<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Role')}</div>

										<div class="flex-1">
											<select
												class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
												bind:value={_user.role}
												aria-label={$i18n.t('Role')}
												disabled={_user.id == sessionUser.id}
												required
											>
												<option value="admin">{$i18n.t('Admin')}</option>
												<option value="user">{$i18n.t('User')}</option>
												<option value="pending">{$i18n.t('Pending')}</option>
											</select>
										</div>
									</div>

									<div class="flex flex-col w-full">
										<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Name')}</div>

										<div class="flex-1">
											<input
												class="w-full text-sm bg-transparent outline-hidden"
												type="text"
												bind:value={_user.name}
												aria-label={$i18n.t('Name')}
												placeholder={$i18n.t('Enter Your Name')}
												autocomplete="off"
												required
											/>
										</div>
									</div>

									<div class="flex flex-col w-full">
										<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Email')}</div>

										<div class="flex-1">
											<input
												class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
												type="email"
												bind:value={_user.email}
												aria-label={$i18n.t('Email')}
												placeholder={$i18n.t('Enter Your Email')}
												autocomplete="off"
												required
											/>
										</div>
									</div>

									{#if _user?.oauth}
										<div class="flex flex-col w-full">
											<div class=" mb-1 text-xs text-gray-500">{$i18n.t('OAuth ID')}</div>

											<div class="flex-1 text-sm break-all mb-1 flex flex-col space-y-1">
												{#each Object.keys(_user.oauth) as key}
													<div>
														<span class="text-gray-500">{key}</span>
														<span class="">{_user.oauth[key]?.sub}</span>
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<div class="flex flex-col w-full">
										<div class=" mb-1 text-xs text-gray-500">{$i18n.t('New Password')}</div>

										<div class="flex-1">
											<SensitiveInput
												class="w-full text-sm bg-transparent outline-hidden"
												type="password"
												aria-label={$i18n.t('New Password')}
												placeholder={$i18n.t('Enter New Password')}
												bind:value={_user.password}
												autocomplete="new-password"
												required={false}
											/>
										</div>
									</div>
								</div>
							</div>
						</div>

						<div class="mt-4">
							<label
								for="admin-user-variables"
								class="mb-1 block text-xs text-gray-500"
							>
								{$i18n.t('User Variables (JSON)')}
							</label>

							<textarea
								id="admin-user-variables"
								class="w-full rounded-lg border border-gray-200 bg-transparent p-2 font-mono text-xs dark:border-gray-700"
								rows="8"
								spellcheck="false"
								bind:value={variablesJson}
								disabled={!variablesLoaded || saving}
							></textarea>

							{#if variablesLoadError}
								<p class="mt-1 text-xs text-red-500" role="alert">
									{variablesLoadError}
								</p>
								<button
									type="button"
									class="mt-1 text-xs underline"
									on:click={() => init()}
								>
									{$i18n.t('Retry')}
								</button>
							{:else if !variablesLoaded}
								<p class="mt-1 text-xs text-gray-500">
									{$i18n.t('Loading variables...')}
								</p>
							{:else}
								<p class="mt-1 text-xs text-gray-500">
									{$i18n.t('Enter a JSON object with string values (Keys must be lowercase). Use {} to clear all variables.')}
								</p>
							{/if}
						</div>

						<div class="flex justify-between pt-3 text-sm font-normal">
							<button
								type="button"
								class="text-sm text-gray-500 transition-colors hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
								on:click={() => {
									showRevokeConfirmation = true;
								}}>{$i18n.t('Sign out all devices')}</button
							>
							<button
								class="flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-gray-900 px-2.5 text-xs font-normal text-white transition hover:bg-black disabled:opacity-60 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
								type="submit"
								disabled={!variablesLoaded || saving}
							>
								{$i18n.t('Save')}
							</button>
						</div>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		-moz-appearance: textfield; /* Firefox */
	}
</style>
