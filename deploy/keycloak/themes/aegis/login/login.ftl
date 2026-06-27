<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
  <#if section = "header">
    <div class="aegis-brand" aria-label="Aegis AI Governance Platform">
      <div class="aegis-logo" aria-hidden="true">A</div>
      <div class="aegis-product">Aegis</div>
      <div class="aegis-subtitle">AI Governance Platform</div>
    </div>
  <#elseif section = "form">
    <div class="aegis-card">
      <div class="aegis-card-header">
        <h1>${msg("doLogIn")}</h1>
        <p>Use your organisation credentials to continue.</p>
      </div>

      <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
        <div class="aegis-alert aegis-alert-${message.type}" role="alert">
          ${kcSanitize(message.summary)?no_esc}
        </div>
      </#if>

      <#if realm.password>
        <form id="kc-form-login" class="aegis-form" action="${url.loginAction}" method="post" onsubmit="login.disabled = true; return true;">
          <label class="aegis-field" for="username">
            <span>
              <#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if>
            </span>
            <input
              tabindex="1"
              id="username"
              name="username"
              value="${(login.username!'')}"
              type="text"
              autofocus
              autocomplete="username"
              aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
            />
          </label>

          <label class="aegis-field" for="password">
            <span>${msg("password")}</span>
            <input
              tabindex="2"
              id="password"
              name="password"
              type="password"
              autocomplete="current-password"
              aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
            />
          </label>

          <#if messagesPerField.existsError('username','password')>
            <div class="aegis-field-error" id="input-error" role="alert">
              ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
            </div>
          </#if>

          <div class="aegis-options">
            <#if realm.rememberMe && !usernameEditDisabled??>
              <label class="aegis-check" for="rememberMe">
                <input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if> />
                <span>${msg("rememberMe")}</span>
              </label>
            </#if>
            <#if realm.resetPasswordAllowed>
              <a tabindex="5" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
            </#if>
          </div>

          <#if auth.selectedCredential?has_content>
            <input type="hidden" name="credentialId" value="${auth.selectedCredential}" />
          </#if>

          <button tabindex="4" class="aegis-submit" name="login" id="kc-login" type="submit">
            ${msg("doLogIn")}
          </button>
        </form>
      </#if>
    </div>

    <div class="aegis-footer">
      <div>All sessions are policy-checked and audited</div>
      <small>Aegis AI Governance Platform</small>
    </div>
  <#elseif section = "info">
    <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
      <div class="aegis-info">
        ${msg("noAccount")} <a tabindex="6" href="${url.registrationUrl}">${msg("doRegister")}</a>
      </div>
    </#if>
  </#if>
</@layout.registrationLayout>
