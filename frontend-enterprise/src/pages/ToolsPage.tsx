import {
  ArrowLeftOutlined,
  DeleteOutlined,
  DownOutlined,
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
  TeamOutlined,
  ToolOutlined,
} from '../icons';
import { AutoComplete, Button, Card, Dropdown, Form, Input, Modal, Select, Space, Switch, Table, Tag, Typography, message } from 'antd';
import type { FormInstance } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, TENANT_ID } from '../api/client';
import CodeBlock from '../components/CodeBlock';
import type { AgentProfileRead, ToolRead } from '../types';

const ENTERPRISE_AGENT_STORAGE_KEY = 'ultrarag_enterprise_agent_scope';
const TOOL_FORM_INITIAL_VALUES = {
  tool_type: 'http',
  method: 'POST',
  enabled: true,
  bucket: '未分桶',
  headers: '{}',
  auth: '{}',
  mcp_config: '{}',
  input_schema: '{}',
  output_schema: '{}',
};

type ToolFormValues = typeof TOOL_FORM_INITIAL_VALUES & {
  name?: string;
  display_name?: string;
  description?: string;
  allowed_skills?: string;
  url?: string;
};

export default function ToolsPage() {
  const [rows, setRows] = useState<ToolRead[]>([]);
  const [agentId, setAgentId] = useState(() => window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '');
  const [isOverallAgent, setIsOverallAgent] = useState(true);
  const [agentScopeLoaded, setAgentScopeLoaded] = useState(false);
  const [bucketFilter, setBucketFilter] = useState('__all__');
  const [searchText, setSearchText] = useState('');
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const agentQuery = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
  const load = () =>
    api
      .get<ToolRead[]>(`/api/enterprise/tools?tenant_id=${TENANT_ID}${agentQuery}`)
      .then(setRows)
      .catch((error) => message.error(error.message));

  useEffect(() => {
    load();
  }, [agentQuery]);

  useEffect(() => {
    const loadAgentScope = async () => {
      try {
        const agents = await api.get<AgentProfileRead[]>(`/api/enterprise/agents?tenant_id=${TENANT_ID}`);
        const selectedAgent = agents.find((agent) => agent.id === agentId) || agents.find((agent) => agent.is_overall) || null;
        setIsOverallAgent(Boolean(selectedAgent?.is_overall));
        setAgentScopeLoaded(true);
      } catch {
        setIsOverallAgent(true);
        setAgentScopeLoaded(true);
      }
    };
    void loadAgentScope();
  }, [agentId]);

  useEffect(() => {
    const onScopeChange = (event: Event) => {
      const nextAgentId = (event as CustomEvent<{ agentId?: string }>).detail?.agentId || window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '';
      setAgentId(nextAgentId);
    };
    window.addEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
    return () => window.removeEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
  }, []);

  useEffect(() => {
    if (searchParams.get('add') !== 'plaza') return;
    if (!agentScopeLoaded) return;
    if (isOverallAgent) {
      message.warning('请先选择一个数字员工，再从广场复制工具');
    } else {
      handleCreateAction('plaza');
    }
    const next = new URLSearchParams(searchParams);
    next.delete('add');
    setSearchParams(next, { replace: true });
  }, [agentScopeLoaded, isOverallAgent, searchParams, setSearchParams]);

  async function remove(row: ToolRead) {
    Modal.confirm({
      title: '删除工具？',
      content: `确认删除「${row.display_name || row.name}」？删除后，引用该工具的技能将无法继续调用它。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const agentQuery = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
        await api.delete(`/api/enterprise/tools/${row.id}?tenant_id=${TENANT_ID}${agentQuery}`);
        message.success('已删除');
        load();
      },
    });
  }

  const columns: ColumnsType<ToolRead> = [
    { title: '工具名称', dataIndex: 'name', width: 170, ellipsis: true },
    { title: '展示名称', dataIndex: 'display_name', width: 160, ellipsis: true },
    {
      title: '分桶',
      dataIndex: 'bucket',
      width: 130,
      render: (value) => <Tag className="tool-bucket-tag">{value || '未分桶'}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'tool_type',
      width: 88,
      render: (value) => <Tag color={value === 'mcp' ? 'geekblue' : undefined}>{value === 'mcp' ? 'MCP' : 'HTTP'}</Tag>,
    },
    { title: 'Method', dataIndex: 'method', width: 96 },
    { title: 'URL', dataIndex: 'url', width: 280, ellipsis: true },
    { title: '启用', dataIndex: 'enabled', width: 80, render: (value) => (value ? '是' : '否') },
    {
      title: '操作',
      width: 244,
      render: (_, row) => (
        <span className="table-actions">
          <Button size="small" onClick={() => navigate(`/enterprise/tools/${row.id}/edit`)}>编辑</Button>
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => navigate(`/enterprise/tools/${row.id}/test`)}>测试</Button>
          {isOverallAgent && <Button size="small" danger icon={<DeleteOutlined />} onClick={() => void remove(row)}>删除</Button>}
        </span>
      ),
    },
  ];

  const visibleRows = useMemo(() => (isOverallAgent ? rows : rows.filter((row) => row.enabled)), [isOverallAgent, rows]);
  const bucketStats = useMemo(() => buildBucketStats(visibleRows), [visibleRows]);
  const filteredRows = useMemo(() => {
    const text = searchText.trim().toLowerCase();
    return visibleRows.filter((row) => {
      const bucketMatch = bucketFilter === '__all__' || (row.bucket || '未分桶') === bucketFilter;
      if (!bucketMatch) return false;
      if (!text) return true;
      return [
        row.name,
        row.display_name || '',
        row.description || '',
        row.bucket || '',
        row.url,
      ].some((value) => value.toLowerCase().includes(text));
    });
  }, [bucketFilter, searchText, visibleRows]);

  function handleCreateAction(key: string) {
    if (key === 'blank') {
      navigate('/enterprise/tools/new');
      return;
    }
    if (key === 'plaza') {
      message.warning('请先选择一个数字员工，再从广场复制工具');
      return;
    }
    if (key === 'employee') {
      message.info('从数字员工复制工具会在后续版本接入。');
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <Typography.Title level={3}>{isOverallAgent ? '工具广场' : '工具'}</Typography.Title>
        </div>
      </div>
      <Card
        className="data-card tools-list-card"
        title={isOverallAgent ? '工具广场列表' : '员工工具'}
        extra={(
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'blank', icon: <PlusOutlined />, label: '新建空白工具' },
                  ...(!isOverallAgent ? [{ key: 'plaza', icon: <ToolOutlined />, label: '从广场复制' }] : []),
                  ...(!isOverallAgent ? [{ key: 'employee', icon: <TeamOutlined />, label: '从数字员工复制' }] : []),
                ],
                onClick: ({ key }) => handleCreateAction(key),
              }}
            >
              <Button type="primary" className="create-dropdown-button">
                新增 <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
        )}
      >
        <div className="tool-bucket-strip">
          <button
            className={`tool-bucket-card ${bucketFilter === '__all__' ? 'active' : ''}`}
            type="button"
            onClick={() => setBucketFilter('__all__')}
          >
            <span className="tool-bucket-name">全部工具</span>
            <strong>{visibleRows.length}</strong>
            <span>{visibleRows.filter((row) => row.enabled).length} 个启用</span>
          </button>
          {bucketStats.map((item) => (
            <button
              className={`tool-bucket-card ${bucketFilter === item.bucket ? 'active' : ''}`}
              key={item.bucket}
              type="button"
              onClick={() => setBucketFilter(item.bucket)}
            >
              <span className="tool-bucket-name">{item.bucket}</span>
              <strong>{item.total}</strong>
              <span>{item.enabled} 个启用 · {item.disabled} 个停用</span>
            </button>
          ))}
        </div>
        <div className="tool-filter-bar">
          <Input.Search
            allowClear
            placeholder="搜索工具名称、描述、URL 或分桶"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Typography.Text type="secondary">当前显示 {filteredRows.length} / {visibleRows.length} 个工具</Typography.Text>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={filteredRows}
          pagination={{ pageSize: 8 }}
          scroll={{ x: 1080 }}
          size="middle"
        />
      </Card>
    </>
  );
}

export function ToolNewPage() {
  return <ToolEditorPage mode="new" />;
}

export function ToolEditPage() {
  return <ToolEditorPage mode="edit" />;
}

function ToolEditorPage({ mode }: { mode: 'new' | 'edit' }) {
  const [form] = Form.useForm<ToolFormValues>();
  const [tool, setTool] = useState<ToolRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [bucketOptions, setBucketOptions] = useState<{ value: string; label: string }[]>([{ value: '未分桶', label: '未分桶' }]);
  const navigate = useNavigate();
  const { toolId } = useParams();
  const isEdit = mode === 'edit';

  useEffect(() => {
    void loadBucketOptions().then(setBucketOptions);
  }, []);

  useEffect(() => {
    if (!isEdit) {
      form.setFieldsValue(TOOL_FORM_INITIAL_VALUES);
      setTool(null);
      return;
    }
    if (!toolId) return;
    setLoading(true);
    const agentQuery = currentAgentQuery();
    api
      .get<ToolRead>(`/api/enterprise/tools/${toolId}?tenant_id=${TENANT_ID}${agentQuery}`)
      .then((row) => {
        setTool(row);
        form.setFieldsValue(toolToFormValues(row));
      })
      .catch((error) => message.error(error instanceof Error ? error.message : '加载工具失败'))
      .finally(() => setLoading(false));
  }, [form, isEdit, toolId]);

  async function save() {
    let values: ToolFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload = buildToolPayload(values);
    if (!payload) return;
    setLoading(true);
    try {
      const agentQuery = currentAgentQuery();
      const saved = isEdit && toolId
        ? await api.put<ToolRead>(`/api/enterprise/tools/${toolId}${agentQuery ? `?${agentQuery.slice(1)}` : ''}`, payload)
        : await api.post<ToolRead>(`/api/enterprise/tools${agentQuery ? `?${agentQuery.slice(1)}` : ''}`, payload);
      message.success('已保存');
      setTool(saved);
      form.setFieldsValue(toolToFormValues(saved));
      if (!isEdit) {
        navigate(`/enterprise/tools/${saved.id}/edit`, { replace: true });
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <Typography.Title level={3}>{isEdit ? '编辑工具' : '新建空白工具'}</Typography.Title>
          <Typography.Text type="secondary">
            {isEdit ? '修改工具定义，并在右侧验证当前配置或已保存版本。' : '填写工具定义后，可先用右侧探测区测试请求与返回结构。'}
          </Typography.Text>
        </div>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/enterprise/tools')}>返回工具</Button>
          {isEdit && tool && (
            <Button icon={<ExperimentOutlined />} onClick={() => navigate(`/enterprise/tools/${tool.id}/test`)}>
              打开测试页
            </Button>
          )}
          <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={() => void save()}>保存</Button>
        </Space>
      </div>
      <div className="grid-2">
        <Card className="editor-card" title="工具定义" loading={loading && isEdit && !tool}>
          <ToolFormFields form={form} bucketOptions={bucketOptions} />
        </Card>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <ToolProbeCard form={form} />
          {isEdit && tool && <SavedToolTestCard tool={tool} />}
        </Space>
      </div>
    </>
  );
}

export function ToolTestPage() {
  const [tool, setTool] = useState<ToolRead | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { toolId } = useParams();

  useEffect(() => {
    if (!toolId) return;
    setLoading(true);
    const agentQuery = currentAgentQuery();
    api
      .get<ToolRead>(`/api/enterprise/tools/${toolId}?tenant_id=${TENANT_ID}${agentQuery}`)
      .then(setTool)
      .catch((error) => message.error(error instanceof Error ? error.message : '加载工具失败'))
      .finally(() => setLoading(false));
  }, [toolId]);

  return (
    <>
      <div className="page-title">
        <div>
          <Typography.Title level={3}>工具测试</Typography.Title>
          <Typography.Text type="secondary">
            用测试参数直接调用已保存工具，检查员工后续调用时的实际返回。
          </Typography.Text>
        </div>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/enterprise/tools')}>返回工具</Button>
          {tool && <Button onClick={() => navigate(`/enterprise/tools/${tool.id}/edit`)}>编辑工具</Button>}
        </Space>
      </div>
      <div className="tool-test-layout">
        <Card className="tool-test-overview-card" title="工具信息" loading={loading && !tool}>
          {tool && (
            <div className="tool-test-overview">
              <div className="tool-test-hero">
                <div className="tool-test-icon">
                  <ToolOutlined />
                </div>
                <div className="tool-test-hero-main">
                  <Typography.Text className="tool-test-eyebrow">{tool.bucket || '未分桶'}</Typography.Text>
                  <Typography.Title level={4}>{tool.display_name || tool.name}</Typography.Title>
                  <Typography.Paragraph type="secondary">{tool.description || '暂无描述'}</Typography.Paragraph>
                  <Space wrap>
                    <Tag color={tool.tool_type === 'mcp' ? 'geekblue' : undefined}>{toolTypeLabel(tool)}</Tag>
                    <Tag color={tool.enabled ? 'green' : 'default'}>{tool.enabled ? '已启用' : '已停用'}</Tag>
                    <Tag>{tool.method}</Tag>
                  </Space>
                </div>
              </div>
              <div className="tool-test-meta-grid">
                <div>
                  <span>工具 ID</span>
                  <strong>{tool.name}</strong>
                </div>
                <div>
                  <span>输入字段</span>
                  <strong>{schemaPropertyCount(tool.input_schema)}</strong>
                </div>
                <div>
                  <span>输出字段</span>
                  <strong>{schemaPropertyCount(tool.output_schema)}</strong>
                </div>
                <div>
                  <span>最近更新</span>
                  <strong>{formatDateTime(tool.updated_at)}</strong>
                </div>
              </div>
              <div className="tool-test-endpoint">
                <span>调用地址</span>
                <code>{tool.method} {tool.url}</code>
              </div>
              <div className="tool-test-schema-grid">
                <div className="tool-test-schema-panel">
                  <div className="tool-test-section-title">Input Schema</div>
                  <CodeBlock className="tool-test-code" code={formatJson(tool.input_schema)} language="json" />
                </div>
                <div className="tool-test-schema-panel">
                  <div className="tool-test-section-title">Output Schema</div>
                  <CodeBlock className="tool-test-code" code={formatJson(tool.output_schema)} language="json" />
                </div>
              </div>
            </div>
          )}
        </Card>
        {tool && <SavedToolTestCard tool={tool} standalone />}
      </div>
    </>
  );
}

function ToolFormFields({
  form,
  bucketOptions,
}: {
  form: FormInstance<ToolFormValues>;
  bucketOptions: { value: string; label: string }[];
}) {
  const toolType = Form.useWatch('tool_type', form) || 'http';
  return (
    <Form form={form} layout="vertical" initialValues={TOOL_FORM_INITIAL_VALUES}>
      <Form.Item name="name" label="工具名称" rules={[{ required: true }]}>
        <Input prefix={<ToolOutlined />} />
      </Form.Item>
      <Form.Item name="display_name" label="展示名称"><Input /></Form.Item>
      <Form.Item name="tool_type" label="工具类型" rules={[{ required: true }]}>
        <Select
          options={[
            { value: 'http', label: 'HTTP 接口' },
            { value: 'mcp', label: 'MCP 服务' },
          ]}
        />
      </Form.Item>
      <Form.Item name="bucket" label="工具分桶">
        <AutoComplete placeholder="选择或输入分桶" options={bucketOptions} />
      </Form.Item>
      <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
      <Form.Item name="method" label={toolType === 'mcp' ? 'Method 标记' : 'HTTP Method'}>
        <Select options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({ value, label: value }))} />
      </Form.Item>
      <Form.Item name="url" label={toolType === 'mcp' ? 'MCP URL 标记' : 'URL'} rules={[{ required: true }]}>
        <Input placeholder={toolType === 'mcp' ? 'mcp://builtin.demo/echo' : '/api/mock/order/query'} />
      </Form.Item>
      {toolType === 'mcp' ? (
        <Form.Item name="mcp_config" label="MCP Config JSON" rules={[{ required: true }]}>
          <Input.TextArea rows={4} placeholder={'{\n  "server": "builtin.demo",\n  "tool": "echo"\n}'} />
        </Form.Item>
      ) : (
        <>
          <Form.Item name="headers" label="Headers JSON"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="auth" label="Auth JSON"><Input.TextArea rows={3} /></Form.Item>
        </>
      )}
      <Form.Item name="input_schema" label="Input Schema"><Input.TextArea rows={5} /></Form.Item>
      <Form.Item name="output_schema" label="Output Schema"><Input.TextArea rows={5} /></Form.Item>
      <Form.Item name="allowed_skills" label="Allowed Skills"><Input placeholder="skill_id_1,skill_id_2" /></Form.Item>
      <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
    </Form>
  );
}

function ToolProbeCard({ form }: { form: FormInstance<ToolFormValues> }) {
  const [sampleJson, setSampleJson] = useState('{}');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const method = Form.useWatch('method', form) || 'POST';
  const isGetMethod = method === 'GET';

  async function probe() {
    let values: ToolFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload = buildToolPayload(values);
    if (!payload) return;
    let sampleArguments: Record<string, unknown>;
    try {
      sampleArguments = parseJson(sampleJson, {});
    } catch {
      message.error('测试参数不是合法 JSON');
      return;
    }
    if (
      payload.tool_type === 'http'
      && payload.method !== 'GET'
      && payload.url.includes('?')
      && Object.keys(sampleArguments).length === 0
    ) {
      message.error('URL 已包含查询参数时请把 HTTP Method 切换为 GET；POST 会把测试参数作为 JSON Body 发送。');
      return;
    }
    setLoading(true);
    try {
      const response = await api.post('/api/enterprise/tools/probe', {
        tenant_id: TENANT_ID,
        name: payload.name,
        display_name: payload.display_name,
        description: payload.description,
        bucket: payload.bucket,
        tool_type: payload.tool_type,
        method: payload.method,
        url: payload.url,
        headers: payload.headers,
        auth: payload.auth,
        mcp_config: payload.mcp_config,
        input_schema: payload.input_schema,
        output_schema: payload.output_schema,
        sample_arguments: sampleArguments,
      });
      setResult(JSON.stringify(response, null, 2));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '探测失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card
      className="editor-card"
      title="配置探测"
      extra={<Button icon={<ExperimentOutlined />} loading={loading} onClick={() => void probe()}>探测</Button>}
    >
      <Typography.Paragraph type="secondary">
        无需保存，直接用当前配置测试连接。
      </Typography.Paragraph>
      <div className="tool-test-section-title">
        {isGetMethod ? '测试参数 JSON（拼到 URL Query）' : '测试参数 JSON（作为请求 Body）'}
      </div>
      <Typography.Paragraph type="secondary" className="tool-probe-hint">
        {isGetMethod
          ? 'GET 会把这里的字段作为查询参数追加到 URL；参数值填写未编码原文，例如 timezone 用 Asia/Shanghai。'
          : '非 GET 请求会把这里的 JSON 作为请求体发送；仅 URL 查询串不会变成请求 Body。'}
      </Typography.Paragraph>
      <Input.TextArea rows={5} value={sampleJson} onChange={(event) => setSampleJson(event.target.value)} />
      <div className="tool-test-section-title tool-test-result-label">探测结果</div>
      <Input.TextArea rows={8} value={result} readOnly style={{ marginTop: 12 }} />
    </Card>
  );
}

function SavedToolTestCard({ tool, standalone = false }: { tool: ToolRead; standalone?: boolean }) {
  const [testJson, setTestJson] = useState(() => JSON.stringify(exampleFromSchema(tool.input_schema), null, 2));
  const [testResult, setTestResult] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setTestJson(JSON.stringify(exampleFromSchema(tool.input_schema), null, 2));
    setTestResult('');
  }, [tool.id, tool.input_schema]);

  async function test() {
    let argumentsJson: Record<string, unknown>;
    try {
      argumentsJson = parseJson(testJson, {});
    } catch {
      message.error('测试参数不是合法 JSON');
      return;
    }
    setLoading(true);
    try {
      const agentQuery = currentAgentQuery();
      const response = await api.post(`/api/enterprise/tools/${tool.id}/test${agentQuery ? `?${agentQuery.slice(1)}` : ''}`, {
        tenant_id: TENANT_ID,
        arguments: argumentsJson,
      });
      setTestResult(JSON.stringify(response, null, 2));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '调用失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card
      className="tool-test-console-card"
      title={(
        <span className="tool-test-card-title">
          <ExperimentOutlined />
          {standalone ? '调用测试' : '已保存工具测试'}
        </span>
      )}
      extra={<Button type="primary" icon={<ExperimentOutlined />} loading={loading} onClick={() => void test()}>调用</Button>}
    >
      <div className="tool-test-console-intro">
        <Typography.Text type="secondary">
          调用已保存的「{tool.display_name || tool.name}」，用于验证员工实际可用的工具返回。
        </Typography.Text>
        <Tag>{toolTypeLabel(tool)}</Tag>
      </div>
      <div className="tool-test-editor-block">
        <div className="tool-test-section-title">测试参数</div>
        <Input.TextArea
          className="tool-test-json-input"
          autoSize={{ minRows: 6, maxRows: 12 }}
          value={testJson}
          onChange={(event) => setTestJson(event.target.value)}
        />
      </div>
      <div className="tool-test-editor-block">
        <div className="tool-test-result-head">
          <div className="tool-test-section-title">调用结果</div>
          <Tag color={testResult ? 'green' : 'default'}>{testResult ? '已返回' : '等待调用'}</Tag>
        </div>
        {testResult ? (
          <CodeBlock className="tool-test-result-code" code={testResult} language="json" />
        ) : (
          <div className="tool-test-empty-result">点击调用后，这里会显示工具返回、错误信息和原始 data。</div>
        )}
      </div>
    </Card>
  );
}

async function loadBucketOptions() {
  const rows = await api.get<ToolRead[]>(`/api/enterprise/tools?tenant_id=${TENANT_ID}${currentAgentQuery()}`);
  return Array.from(new Set(['未分桶', ...rows.map((row) => row.bucket || '未分桶')]))
    .map((value) => ({ value, label: value }));
}

function currentAgentQuery() {
  const agentId = window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '';
  return agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
}

function toolToFormValues(row: ToolRead): ToolFormValues {
  return {
    ...TOOL_FORM_INITIAL_VALUES,
    ...row,
    bucket: row.bucket || '未分桶',
    tool_type: row.tool_type || 'http',
    headers: JSON.stringify(row.headers || {}, null, 2),
    auth: JSON.stringify(row.auth || {}, null, 2),
    mcp_config: JSON.stringify(row.mcp_config || {}, null, 2),
    input_schema: JSON.stringify(row.input_schema || {}, null, 2),
    output_schema: JSON.stringify(row.output_schema || {}, null, 2),
    allowed_skills: (row.allowed_skills || []).join(','),
  };
}

function buildToolPayload(values: ToolFormValues) {
  try {
    return {
      tenant_id: TENANT_ID,
      name: String(values.name || '').trim(),
      display_name: values.display_name,
      description: values.description,
      bucket: values.bucket || '未分桶',
      tool_type: values.tool_type || 'http',
      method: values.method,
      url: String(values.url || '').trim(),
      headers: parseJson(values.headers, {}),
      auth: parseJson(values.auth, {}),
      mcp_config: values.tool_type === 'mcp' ? parseJson(values.mcp_config, {}) : {},
      input_schema: parseJson(values.input_schema, {}),
      output_schema: parseJson(values.output_schema, {}),
      allowed_skills: String(values.allowed_skills || '').split(',').map((item) => item.trim()).filter(Boolean),
      enabled: values.enabled,
    };
  } catch {
    message.error('JSON 配置格式不正确，请检查 Headers、Auth、Schema 或 MCP Config');
    return null;
  }
}

function buildBucketStats(rows: ToolRead[]) {
  const map = new Map<string, { bucket: string; total: number; enabled: number; disabled: number }>();
  rows.forEach((row) => {
    const bucket = row.bucket || '未分桶';
    const item = map.get(bucket) || { bucket, total: 0, enabled: 0, disabled: 0 };
    item.total += 1;
    if (row.enabled) item.enabled += 1;
    else item.disabled += 1;
    map.set(bucket, item);
  });
  return Array.from(map.values()).sort((a, b) => b.total - a.total || a.bucket.localeCompare(b.bucket));
}

function parseJson<T>(value: string, fallback: T): T {
  if (!value) return fallback;
  return JSON.parse(value) as T;
}

function formatJson(value: unknown): string {
  return JSON.stringify(value || {}, null, 2);
}

function schemaPropertyCount(schema: Record<string, unknown>): string {
  const properties = schema.properties && typeof schema.properties === 'object'
    ? schema.properties as Record<string, unknown>
    : {};
  return `${Object.keys(properties).length}`;
}

function toolTypeLabel(tool: ToolRead): string {
  return tool.tool_type === 'mcp' ? 'MCP 服务' : 'HTTP 接口';
}

function formatDateTime(value: string): string {
  if (!value) return '-';
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false });
}

function exampleFromSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = schema.properties && typeof schema.properties === 'object'
    ? schema.properties as Record<string, Record<string, unknown>>
    : {};
  return Object.fromEntries(
    Object.entries(properties).map(([key, value]) => [key, exampleValue(key, value)]),
  );
}

function exampleValue(key: string, schema: Record<string, unknown>): unknown {
  if (schema.default !== undefined) return schema.default;
  if (schema.example !== undefined) return schema.example;
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0];
  if (schema.type === 'integer') return 1;
  if (schema.type === 'number') return 1;
  if (schema.type === 'boolean') return true;
  if (schema.type === 'array') return [];
  if (schema.type === 'object') return {};
  return `sample_${key}`;
}
