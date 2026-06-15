import {
  CheckOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  FileSearchOutlined,
  HistoryOutlined,
  InboxOutlined,
  MoreOutlined,
  ReloadOutlined,
  RightOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { Button, Card, Col, Collapse, Dropdown, Empty, Input, Modal, Progress, Row, Select, Space, Table, Tag, Typography, Upload, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, TENANT_ID } from '../api/client';
import type {
  KnowledgeBaseRead,
  KnowledgeBucketRead,
  KnowledgeChunkRead,
  KnowledgeDiscoveryRead,
  KnowledgeDocumentRead,
  KnowledgeIngestJobRead,
  AgentProfileRead,
} from '../types';

const { Dragger } = Upload;
const ENTERPRISE_AGENT_STORAGE_KEY = 'ultrarag_enterprise_agent_scope';

type KnowledgeBaseVersionRead = {
  id: string;
  version: string;
  name: string;
  description?: string;
  status: string;
  is_head: boolean;
  is_base: boolean;
  updated_at: string;
  created_at: string;
};

export default function KnowledgeManagePage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<KnowledgeDocumentRead[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseRead[]>([]);
  const [discoveries, setDiscoveries] = useState<KnowledgeDiscoveryRead[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocumentRead | null>(null);
  const [buckets, setBuckets] = useState<KnowledgeBucketRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [agentId, setAgentId] = useState(() => window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '');
  const [agents, setAgents] = useState<AgentProfileRead[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [importSourceAgentId, setImportSourceAgentId] = useState('');
  const [importSourceKnowledgeBases, setImportSourceKnowledgeBases] = useState<KnowledgeBaseRead[]>([]);
  const [importSelectedKnowledgeBaseIds, setImportSelectedKnowledgeBaseIds] = useState<string[]>([]);
  const [importLoading, setImportLoading] = useState(false);
  const [editingKnowledgeBase, setEditingKnowledgeBase] = useState<KnowledgeBaseRead | null>(null);
  const [knowledgeBaseDraft, setKnowledgeBaseDraft] = useState({ name: '', description: '', status: 'active' });
  const [versionKnowledgeBase, setVersionKnowledgeBase] = useState<KnowledgeBaseRead | null>(null);
  const [knowledgeBaseVersions, setKnowledgeBaseVersions] = useState<KnowledgeBaseVersionRead[]>([]);
  const [editingDocument, setEditingDocument] = useState<KnowledgeDocumentRead | null>(null);
  const [documentDraft, setDocumentDraft] = useState({ title: '', status: 'ready' });
  const [editingBucket, setEditingBucket] = useState<KnowledgeBucketRead | null>(null);
  const [bucketDraft, setBucketDraft] = useState({ title: '', summary: '' });
  const [bucketChunks, setBucketChunks] = useState<KnowledgeChunkRead[]>([]);
  const [chunkDrafts, setChunkDrafts] = useState<Record<string, { content: string; summary: string }>>({});
  const [contentSaving, setContentSaving] = useState(false);

  const actionableDiscoveries = discoveries.filter((item) => item.status === 'pending' && item.suggestion_type !== 'warning');
  const warningDiscoveries = discoveries.filter((item) => item.suggestion_type === 'warning' || item.status !== 'pending');
  const currentAgent = useMemo(() => agents.find((item) => item.id === agentId), [agents, agentId]);
  const isOverallAgent = !currentAgent || currentAgent.is_overall;

  useEffect(() => {
    void refresh();
  }, [agentId]);

  useEffect(() => {
    const onScopeChange = (event: Event) => {
      setAgentId((event as CustomEvent<{ agentId?: string }>).detail?.agentId || window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '');
    };
    window.addEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
    return () => window.removeEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
  }, []);

  async function refresh() {
    setLoading(true);
    const suffix = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
    try {
      const [docRows, discoveryRows, kbRows, agentRows] = await Promise.all([
        api.get<KnowledgeDocumentRead[]>(`/api/enterprise/knowledge/documents?tenant_id=${TENANT_ID}${suffix}`),
        api.get<KnowledgeDiscoveryRead[]>(`/api/enterprise/knowledge/discoveries?tenant_id=${TENANT_ID}${suffix}`),
        api.get<KnowledgeBaseRead[]>(`/api/enterprise/knowledge-bases?tenant_id=${TENANT_ID}${suffix}`),
        api.get<AgentProfileRead[]>(`/api/enterprise/agents?tenant_id=${TENANT_ID}`),
      ]);
      setDocuments(docRows);
      setDiscoveries(discoveryRows);
      setKnowledgeBases(kbRows);
      setAgents(agentRows);
      const current = selectedDocument ? docRows.find((item) => item.id === selectedDocument.id) || null : docRows[0] || null;
      setSelectedDocument(current);
      if (current) {
        await loadBuckets(current, false);
      } else {
        setBuckets([]);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '刷新知识库失败');
    } finally {
      setLoading(false);
    }
  }

  async function loadBuckets(document: KnowledgeDocumentRead, select = true) {
    if (select) setSelectedDocument(document);
    try {
      const rows = await api.get<KnowledgeBucketRead[]>(
        `/api/enterprise/knowledge/documents/${document.id}/buckets?tenant_id=${TENANT_ID}`,
      );
      setBuckets(rows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载知识桶失败');
    }
  }

  async function confirmDiscovery(item: KnowledgeDiscoveryRead) {
    try {
      await api.post(`/api/enterprise/knowledge/discoveries/${item.id}/confirm?tenant_id=${TENANT_ID}`);
      message.success('已确认建议');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '确认失败');
    }
  }

  async function rejectDiscovery(item: KnowledgeDiscoveryRead) {
    try {
      await api.post(`/api/enterprise/knowledge/discoveries/${item.id}/reject?tenant_id=${TENANT_ID}`);
      message.success('已拒绝建议');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '拒绝失败');
    }
  }

  async function openImportKnowledgeBases() {
    try {
      const agentRows = agents.length ? agents : await api.get<AgentProfileRead[]>(`/api/enterprise/agents?tenant_id=${TENANT_ID}`);
      setAgents(agentRows);
      const firstSource = agentRows.find((item) => item.id !== agentId)?.id || '';
      setImportSourceAgentId(firstSource);
      setImportSelectedKnowledgeBaseIds([]);
      setImportOpen(true);
      if (firstSource) {
        await loadImportSourceKnowledgeBases(firstSource);
      } else {
        setImportSourceKnowledgeBases([]);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载智能体失败');
    }
  }

  async function loadImportSourceKnowledgeBases(sourceAgentId: string) {
    setImportSourceKnowledgeBases([]);
    setImportSelectedKnowledgeBaseIds([]);
    if (!sourceAgentId) return;
    try {
      const rows = await api.get<KnowledgeBaseRead[]>(
        `/api/enterprise/knowledge-bases?tenant_id=${TENANT_ID}&agent_id=${encodeURIComponent(sourceAgentId)}`,
      );
      setImportSourceKnowledgeBases(rows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载来源知识库失败');
    }
  }

  async function submitImportKnowledgeBases() {
    if (!agentId) {
      message.warning('请先选择目标智能体');
      return;
    }
    if (!importSourceAgentId) {
      message.warning('请选择来源智能体');
      return;
    }
    if (importSelectedKnowledgeBaseIds.length === 0) {
      message.warning('请选择要导入的知识库');
      return;
    }
    setImportLoading(true);
    try {
      const result = await api.post<{ imported: Array<Record<string, unknown>>; missing: Array<Record<string, unknown>> }>(
        `/api/enterprise/agents/${agentId}/resources/import`,
        {
          tenant_id: TENANT_ID,
          source_agent_id: importSourceAgentId,
          resource_type: 'knowledge_base',
          resource_ids: importSelectedKnowledgeBaseIds,
        },
      );
      const importedCount = result.imported?.length || 0;
      const missingCount = result.missing?.length || 0;
      message.success(`已导入 ${importedCount} 个知识库${missingCount ? `，${missingCount} 个未导入` : ''}`);
      setImportOpen(false);
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导入失败');
    } finally {
      setImportLoading(false);
    }
  }

  function openEditKnowledgeBase(row: KnowledgeBaseRead) {
    setEditingKnowledgeBase(row);
    setKnowledgeBaseDraft({
      name: row.name,
      description: row.description || '',
      status: row.status === 'archived' ? 'archived' : 'active',
    });
  }

  async function saveKnowledgeBase() {
    if (!editingKnowledgeBase) return;
    const suffix = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
    try {
      const next = await api.put<KnowledgeBaseRead>(`/api/enterprise/knowledge-bases/${editingKnowledgeBase.id}${suffix}`, {
        tenant_id: TENANT_ID,
        name: knowledgeBaseDraft.name,
        description: knowledgeBaseDraft.description,
        status: knowledgeBaseDraft.status,
      });
      setKnowledgeBases((current) => current.map((item) => (item.id === next.id ? next : item)));
      setEditingKnowledgeBase(null);
      message.success('已保存知识库');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存知识库失败');
    }
  }

  async function setKnowledgeBaseStatus(row: KnowledgeBaseRead, active: boolean) {
    const suffix = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
    try {
      await api.put<KnowledgeBaseRead>(`/api/enterprise/knowledge-bases/${row.id}${suffix}`, {
        tenant_id: TENANT_ID,
        status: active ? 'active' : 'archived',
      });
      message.success(active ? '已上线知识库' : '已下线知识库');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : active ? '上线失败' : '下线失败');
    }
  }

  function deleteKnowledgeBase(row: KnowledgeBaseRead) {
    Modal.confirm({
      title: `删除知识库：${row.name}`,
      content: '只有整体智能体可以删除知识库；有文档的知识库会被归档，避免误删内容。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        const suffix = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
        try {
          await api.delete(`/api/enterprise/knowledge-bases/${row.id}?tenant_id=${TENANT_ID}${suffix}`);
          message.success('已处理删除请求');
          await refresh();
        } catch (error) {
          message.error(error instanceof Error ? error.message : '删除失败');
        }
      },
    });
  }

  async function openKnowledgeBaseVersions(row: KnowledgeBaseRead) {
    const suffix = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
    try {
      const versions = await api.get<KnowledgeBaseVersionRead[]>(
        `/api/enterprise/knowledge-bases/${row.id}/versions?tenant_id=${TENANT_ID}${suffix}`,
      );
      setVersionKnowledgeBase(row);
      setKnowledgeBaseVersions(versions);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载版本失败');
    }
  }

  async function syncKnowledgeBaseFromOverall(row: KnowledgeBaseRead) {
    if (!agentId) {
      message.warning('请先选择智能体');
      return;
    }
    try {
      await api.post(`/api/enterprise/knowledge-bases/${row.id}/sync-from-overall?tenant_id=${TENANT_ID}&agent_id=${encodeURIComponent(agentId)}`);
      message.success('已同步整体知识库');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '同步失败');
    }
  }

  async function promoteKnowledgeBaseToOverall(row: KnowledgeBaseRead) {
    if (!agentId) {
      message.warning('请先选择智能体');
      return;
    }
    try {
      await api.post(`/api/enterprise/knowledge-bases/${row.id}/promote-to-overall?tenant_id=${TENANT_ID}&agent_id=${encodeURIComponent(agentId)}`);
      message.success('已推送到整体知识库');
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '推送失败');
    }
  }

  async function rollbackKnowledgeBaseVersion(version: KnowledgeBaseVersionRead) {
    if (!versionKnowledgeBase || !agentId) return;
    try {
      await api.post(`/api/enterprise/knowledge-bases/${versionKnowledgeBase.id}/rollback`, {
        tenant_id: TENANT_ID,
        agent_id: agentId,
        version: version.version,
      });
      message.success(`已回滚到 ${version.version}`);
      await openKnowledgeBaseVersions(versionKnowledgeBase);
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '回滚失败');
    }
  }

  function openEditDocument(row: KnowledgeDocumentRead) {
    setEditingDocument(row);
    setDocumentDraft({
      title: row.title || row.filename,
      status: row.status,
    });
  }

  async function saveDocument() {
    if (!editingDocument) return;
    try {
      const next = await api.put<KnowledgeDocumentRead>(`/api/enterprise/knowledge/documents/${editingDocument.id}`, {
        tenant_id: TENANT_ID,
        title: documentDraft.title,
        status: documentDraft.status,
      });
      setDocuments((current) => current.map((item) => (item.id === next.id ? next : item)));
      setSelectedDocument((current) => (current?.id === next.id ? next : current));
      setEditingDocument(null);
      message.success('已保存文档');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存文档失败');
    }
  }

  async function openBucketEditor(row: KnowledgeBucketRead) {
    setEditingBucket(row);
    setBucketDraft({ title: row.title, summary: row.summary });
    try {
      const chunks = await api.get<KnowledgeChunkRead[]>(`/api/enterprise/knowledge/buckets/${row.id}/chunks?tenant_id=${TENANT_ID}`);
      setBucketChunks(chunks);
      setChunkDrafts(
        Object.fromEntries(chunks.map((chunk) => [chunk.id, { content: chunk.content, summary: chunk.summary || '' }])),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载片段失败');
    }
  }

  async function saveBucketAndChunks() {
    if (!editingBucket) return;
    setContentSaving(true);
    try {
      await api.put<KnowledgeBucketRead>(`/api/enterprise/knowledge/buckets/${editingBucket.id}`, {
        tenant_id: TENANT_ID,
        title: bucketDraft.title,
        summary: bucketDraft.summary,
      });
      await Promise.all(
        bucketChunks.map((chunk) =>
          api.put<KnowledgeChunkRead>(`/api/enterprise/knowledge/chunks/${chunk.id}`, {
            tenant_id: TENANT_ID,
            content: chunkDrafts[chunk.id]?.content ?? chunk.content,
            summary: chunkDrafts[chunk.id]?.summary ?? chunk.summary,
          }),
        ),
      );
      message.success('已保存知识内容');
      setEditingBucket(null);
      if (selectedDocument) await loadBuckets(selectedDocument, false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存知识内容失败');
    } finally {
      setContentSaving(false);
    }
  }

  const documentColumns: ColumnsType<KnowledgeDocumentRead> = [
    {
      title: '知识',
      dataIndex: 'title',
      render: (_value, row) => (
        <button type="button" className="knowledge-doc-link" onClick={() => void loadBuckets(row)}>
          <span>{row.title || row.filename}</span>
          <small>{row.filename}</small>
        </button>
      ),
    },
    { title: '格式', dataIndex: 'file_type', width: 92, render: (value) => <Tag>{value}</Tag> },
    { title: '状态', dataIndex: 'status', width: 104, render: (value) => statusTag(value) },
    { title: '桶', dataIndex: 'bucket_count', width: 72 },
    { title: '片段', dataIndex: 'chunk_count', width: 72 },
    { title: '更新', dataIndex: 'updated_at', width: 120, render: (value) => String(value).slice(0, 10) },
    {
      title: '操作',
      width: 86,
      render: (_value, row) => (
        <Button size="small" icon={<EditOutlined />} onClick={() => openEditDocument(row)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <div className="knowledge-page knowledge-manage-page">
      <div className="knowledge-hero">
        <div>
          <Typography.Title level={3}>知识管理</Typography.Title>
          <Typography.Text type="secondary">查看已入库文档、分桶切片结果，以及待确认的技能和工具发现。</Typography.Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refresh()} loading={loading}>刷新</Button>
          <Button onClick={() => void openImportKnowledgeBases()}>从智能体导入</Button>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => navigate('/enterprise/knowledge/new')}>
            新增知识
          </Button>
        </Space>
      </div>

      <Row gutter={[18, 18]}>
        <Col xs={24}>
          <Card className="knowledge-card knowledge-card-solid" title="知识库">
            {knowledgeBases.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无知识库" />
            ) : (
              <div className="knowledge-base-grid">
                {knowledgeBases.map((item) => (
                  <div className="knowledge-base-card" key={item.id}>
                    <div className="knowledge-base-card-head">
                      <div>
                        <Typography.Text strong>{item.name}</Typography.Text>
                        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>
                          {item.description || '未填写描述'}
                        </Typography.Paragraph>
                      </div>
                      <Dropdown
                        trigger={['click']}
                        menu={{
                          items: [
                            { key: 'edit', icon: <EditOutlined />, label: '编辑' },
                            { key: 'versions', icon: <HistoryOutlined />, label: '版本管理' },
                            !isOverallAgent ? { key: 'sync', label: '同步整体' } : null,
                            !isOverallAgent ? { key: 'promote', label: '推送到整体' } : null,
                            item.status === 'archived'
                              ? { key: 'publish', label: '上线' }
                              : { key: 'archive', label: '下线' },
                            isOverallAgent ? { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true } : null,
                          ].filter(Boolean),
                          onClick: ({ key }) => {
                            if (key === 'edit') openEditKnowledgeBase(item);
                            if (key === 'versions') void openKnowledgeBaseVersions(item);
                            if (key === 'sync') void syncKnowledgeBaseFromOverall(item);
                            if (key === 'promote') void promoteKnowledgeBaseToOverall(item);
                            if (key === 'publish') void setKnowledgeBaseStatus(item, true);
                            if (key === 'archive') void setKnowledgeBaseStatus(item, false);
                            if (key === 'delete') deleteKnowledgeBase(item);
                          },
                        }}
                      >
                        <Button type="text" size="small" icon={<MoreOutlined />} />
                      </Dropdown>
                    </div>
                    <Space size={6} wrap>
                      {statusTag(item.status)}
                      {item.version && <Tag>v{item.version}</Tag>}
                      {item.branch_sync_state && <Tag color={item.branch_sync_state === 'diverged' ? 'gold' : 'green'}>
                        {item.branch_sync_state === 'diverged' ? '分支修改' : '已同步'}
                      </Tag>}
                      <Tag>{item.document_count} 文档</Tag>
                      <Tag>{item.bucket_count} 桶</Tag>
                      <Tag>{item.chunk_count} 片段</Tag>
                    </Space>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={14}>
          <Card className="knowledge-card knowledge-card-solid" title="现有知识" extra={<DatabaseOutlined />}>
            <Table
              rowKey="id"
              columns={documentColumns}
              dataSource={documents}
              loading={loading}
              pagination={{ pageSize: 8 }}
              rowClassName={(row) => (row.id === selectedDocument?.id ? 'knowledge-row-selected' : '')}
            />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card
            className="knowledge-card knowledge-card-solid"
            title={selectedDocument ? `知识桶 · ${selectedDocument.title || selectedDocument.filename}` : '知识桶'}
            extra={<FileSearchOutlined />}
          >
            {!selectedDocument ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个文档查看知识桶" />
            ) : buckets.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分桶结果" />
            ) : (
              <div className="knowledge-bucket-list">
                {buckets.map((bucket) => (
                  <div className="knowledge-bucket-item" key={bucket.id}>
                    <div className="knowledge-bucket-title">
                      <span>{bucket.title}</span>
                      <Space size={6}>
                        {bucketStatusTag(bucket)}
                        <Button size="small" icon={<EditOutlined />} onClick={() => void openBucketEditor(bucket)}>
                          编辑
                        </Button>
                      </Space>
                    </div>
                    <Typography.Paragraph ellipsis={{ rows: 3 }}>{bucket.summary}</Typography.Paragraph>
                    <div className="knowledge-bucket-meta">
                      <Tag>{bucket.bucket_key}</Tag>
                      <Tag>{bucket.chunk_count} 片段</Tag>
                      <Tag>{bucket.token_estimate} tokens</Tag>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card className="knowledge-card knowledge-card-solid" title="自发现建议">
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={13}>
            <DiscoveryColumn
              title="可确认建议"
              description="模型从知识中发现的技能和工具草案。确认后才会进入系统。"
              items={actionableDiscoveries}
              onConfirm={confirmDiscovery}
              onReject={rejectDiscovery}
            />
          </Col>
          <Col xs={24} lg={11}>
            <DiscoveryColumn
              title="信息与警告"
              description="不满足入库条件、已处理或需要人工补充的信息。"
              items={warningDiscoveries}
              onConfirm={confirmDiscovery}
              onReject={rejectDiscovery}
              readonly
            />
          </Col>
        </Row>
      </Card>
      <Modal
        open={importOpen}
        title="从其他智能体导入知识库"
        width={720}
        okText="导入"
        cancelText="取消"
        confirmLoading={importLoading}
        onOk={() => void submitImportKnowledgeBases()}
        onCancel={() => setImportOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Select
            value={importSourceAgentId || undefined}
            placeholder="选择来源智能体"
            onChange={(value) => {
              setImportSourceAgentId(value);
              void loadImportSourceKnowledgeBases(value);
            }}
            options={agents
              .filter((item) => item.id !== agentId)
              .map((item) => ({
                value: item.id,
                label: `${item.name}${item.is_overall ? '（整体）' : ''}`,
              }))}
            style={{ width: '100%' }}
          />
          <Select
            mode="multiple"
            value={importSelectedKnowledgeBaseIds}
            placeholder="选择一个或多个知识库"
            onChange={setImportSelectedKnowledgeBaseIds}
            options={importSourceKnowledgeBases.map((item) => ({
              value: item.id,
              label: `${item.name} · ${item.version || '1.0.0'} · ${item.status}`,
            }))}
            optionFilterProp="label"
            style={{ width: '100%' }}
          />
          <Typography.Text type="secondary">
            导入会复制来源智能体中选中知识库的分支版本；目标为整体智能体时，会将来源分支推送为整体知识库新版本。
          </Typography.Text>
        </Space>
      </Modal>
      <Modal
        open={Boolean(editingKnowledgeBase)}
        title="编辑知识库"
        okText="保存"
        cancelText="取消"
        onOk={() => void saveKnowledgeBase()}
        onCancel={() => setEditingKnowledgeBase(null)}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Input
            value={knowledgeBaseDraft.name}
            onChange={(event) => setKnowledgeBaseDraft((prev) => ({ ...prev, name: event.target.value }))}
            placeholder="知识库名称"
          />
          <Input.TextArea
            rows={4}
            value={knowledgeBaseDraft.description}
            onChange={(event) => setKnowledgeBaseDraft((prev) => ({ ...prev, description: event.target.value }))}
            placeholder="知识库描述"
          />
          <Select
            value={knowledgeBaseDraft.status}
            onChange={(value) => setKnowledgeBaseDraft((prev) => ({ ...prev, status: value }))}
            options={[
              { value: 'active', label: '上线' },
              { value: 'archived', label: '下线' },
            ]}
          />
        </Space>
      </Modal>
      <Modal
        open={Boolean(versionKnowledgeBase)}
        title={versionKnowledgeBase ? `版本管理：${versionKnowledgeBase.name}` : '版本管理'}
        width={840}
        footer={<Button onClick={() => setVersionKnowledgeBase(null)}>关闭</Button>}
        onCancel={() => setVersionKnowledgeBase(null)}
      >
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={knowledgeBaseVersions}
          columns={[
            { title: '版本', dataIndex: 'version' },
            { title: '名称', dataIndex: 'name' },
            { title: '状态', dataIndex: 'status', render: (value) => statusTag(String(value)) },
            { title: 'Head', dataIndex: 'is_head', render: (value) => (value ? <Tag color="green">当前</Tag> : null) },
            { title: '更新时间', dataIndex: 'updated_at', render: (value) => String(value).slice(0, 10) },
            {
              title: '操作',
              width: 96,
              render: (_value, row) =>
                !isOverallAgent && !row.is_head ? (
                  <Button size="small" onClick={() => void rollbackKnowledgeBaseVersion(row)}>
                    回滚
                  </Button>
                ) : null,
            },
          ]}
        />
      </Modal>
      <Modal
        open={Boolean(editingDocument)}
        title="编辑文档"
        okText="保存"
        cancelText="取消"
        onOk={() => void saveDocument()}
        onCancel={() => setEditingDocument(null)}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Input
            value={documentDraft.title}
            onChange={(event) => setDocumentDraft((prev) => ({ ...prev, title: event.target.value }))}
            placeholder="文档标题"
          />
          <Select
            value={documentDraft.status}
            onChange={(value) => setDocumentDraft((prev) => ({ ...prev, status: value }))}
            options={[
              { value: 'ready', label: '可用' },
              { value: 'processing', label: '处理中' },
              { value: 'failed', label: '失败' },
              { value: 'archived', label: '下线' },
            ]}
          />
        </Space>
      </Modal>
      <Modal
        className="knowledge-editor-modal"
        open={Boolean(editingBucket)}
        title="编辑知识桶与片段"
        width={920}
        okText="保存"
        cancelText="取消"
        confirmLoading={contentSaving}
        onOk={() => void saveBucketAndChunks()}
        onCancel={() => setEditingBucket(null)}
      >
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Input
            value={bucketDraft.title}
            onChange={(event) => setBucketDraft((prev) => ({ ...prev, title: event.target.value }))}
            placeholder="知识桶标题"
          />
          <Input.TextArea
            rows={4}
            value={bucketDraft.summary}
            onChange={(event) => setBucketDraft((prev) => ({ ...prev, summary: event.target.value }))}
            placeholder="知识桶摘要"
          />
          <div className="knowledge-chunk-editor-list">
            {bucketChunks.map((chunk) => (
              <div className="knowledge-chunk-editor" key={chunk.id}>
                <div className="knowledge-chunk-editor-head">
                  <Typography.Text strong>片段 {chunk.chunk_index + 1}</Typography.Text>
                  <Tag>{chunk.source_ref || 'chunk'}</Tag>
                </div>
                <Input.TextArea
                  rows={2}
                  value={chunkDrafts[chunk.id]?.summary || ''}
                  onChange={(event) =>
                    setChunkDrafts((prev) => ({
                      ...prev,
                      [chunk.id]: { ...(prev[chunk.id] || { content: chunk.content, summary: '' }), summary: event.target.value },
                    }))
                  }
                  placeholder="片段摘要"
                />
                <Input.TextArea
                  rows={6}
                  value={chunkDrafts[chunk.id]?.content || ''}
                  onChange={(event) =>
                    setChunkDrafts((prev) => ({
                      ...prev,
                      [chunk.id]: { ...(prev[chunk.id] || { content: '', summary: chunk.summary || '' }), content: event.target.value },
                    }))
                  }
                  placeholder="片段内容"
                />
              </div>
            ))}
          </div>
        </Space>
      </Modal>
    </div>
  );
}

export function KnowledgeAddPage() {
  const navigate = useNavigate();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseRead[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState('');
  const [newKnowledgeBaseName, setNewKnowledgeBaseName] = useState('');
  const [jobs, setJobs] = useState<Record<string, KnowledgeIngestJobRead>>({});
  const [agentId, setAgentId] = useState(() => window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '');
  const activeJobs = useMemo(
    () => Object.values(jobs).filter((job) => ['queued', 'running'].includes(job.status)),
    [jobs],
  );

  useEffect(() => {
    void refreshKnowledgeBases();
  }, [agentId]);

  useEffect(() => {
    const onScopeChange = (event: Event) => {
      setAgentId((event as CustomEvent<{ agentId?: string }>).detail?.agentId || window.localStorage.getItem(ENTERPRISE_AGENT_STORAGE_KEY) || '');
    };
    window.addEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
    return () => window.removeEventListener('ultrarag-enterprise-agent-scope-change', onScopeChange);
  }, []);

  useEffect(() => {
    if (activeJobs.length === 0) return;
    const timer = window.setInterval(() => {
      activeJobs.forEach((job) => {
        void api
          .get<KnowledgeIngestJobRead>(`/api/enterprise/knowledge/jobs/${job.id}?tenant_id=${TENANT_ID}`)
          .then((next) => setJobs((prev) => ({ ...prev, [next.id]: next })))
          .catch(() => undefined);
      });
    }, 1400);
    return () => window.clearInterval(timer);
  }, [activeJobs]);

  async function refreshKnowledgeBases() {
    try {
      const suffix = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : '';
      const rows = await api.get<KnowledgeBaseRead[]>(`/api/enterprise/knowledge-bases?tenant_id=${TENANT_ID}${suffix}`);
      setKnowledgeBases(rows);
      setSelectedKnowledgeBaseId((current) => current || rows.find((item) => item.status === 'active')?.id || rows[0]?.id || '');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载知识库失败');
    }
  }

  async function createKnowledgeBaseWithName(name: string, description = '') {
    if (!name) {
      message.warning('请先输入知识库名称');
      return null;
    }
    try {
      const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
      const row = await api.post<KnowledgeBaseRead>(`/api/enterprise/knowledge-bases${query}`, {
        tenant_id: TENANT_ID,
        name,
        description,
      });
      setKnowledgeBases((prev) => [row, ...prev]);
      setSelectedKnowledgeBaseId(row.id);
      return row;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建知识库失败');
      return null;
    }
  }

  async function createKnowledgeBase() {
    const name = newKnowledgeBaseName.trim();
    const row = await createKnowledgeBaseWithName(name);
    if (row) {
      setNewKnowledgeBaseName('');
      message.success('已创建知识库');
    }
  }

  async function uploadFile(file: File, explicitKnowledgeBaseId?: string) {
    const targetKnowledgeBaseId = explicitKnowledgeBaseId || selectedKnowledgeBaseId;
    if (!targetKnowledgeBaseId) {
      message.warning('请先选择或创建知识库');
      return;
    }
    try {
      const contentBase64 = await fileToBase64(file);
      const suffix = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
      const job = await api.post<KnowledgeIngestJobRead>(`/api/enterprise/knowledge/documents${suffix}`, {
        tenant_id: TENANT_ID,
        knowledge_base_id: targetKnowledgeBaseId,
        filename: file.name,
        title: file.name.replace(/\.[^.]+$/, ''),
        content_base64: contentBase64,
      });
      setJobs((prev) => ({ ...prev, [job.id]: job }));
      message.success('已创建知识入库任务');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '上传失败');
    }
  }

  return (
    <div className="knowledge-page knowledge-add-page">
      <div className="knowledge-hero">
        <div>
          <Typography.Title level={3}>新增知识</Typography.Title>
          <Typography.Text type="secondary">上传业务文档，后台会完成解析、分桶、切片和自发现建议生成。</Typography.Text>
        </div>
        <Button icon={<RightOutlined />} onClick={() => navigate('/enterprise/knowledge')}>查看知识管理</Button>
      </div>

      <Card className="knowledge-card knowledge-upload-card">
        <div className="knowledge-upload-controls">
          <div>
            <Typography.Text strong>归属知识库</Typography.Text>
            <Typography.Text type="secondary">每个上传文档、知识桶和切片都会归属到这里。</Typography.Text>
          </div>
          <Space wrap>
            <Select
              className="knowledge-base-select"
              placeholder="选择知识库"
              value={selectedKnowledgeBaseId || undefined}
              onChange={setSelectedKnowledgeBaseId}
              options={knowledgeBases.map((item) => ({ value: item.id, label: item.name }))}
            />
            <Input
              className="knowledge-base-create-input"
              placeholder="新建知识库名称"
              value={newKnowledgeBaseName}
              onChange={(event) => setNewKnowledgeBaseName(event.target.value)}
              onPressEnter={() => void createKnowledgeBase()}
            />
            <Button onClick={() => void createKnowledgeBase()}>新建知识库</Button>
          </Space>
        </div>
        <Dragger
          multiple
          showUploadList={false}
          beforeUpload={(file) => {
            void uploadFile(file);
            return false;
          }}
          accept=".doc,.docx,.txt,.md,.markdown,.html,.htm,.pdf"
        >
          <div className="knowledge-upload-inner">
            <InboxOutlined />
            <div>
              <strong>拖拽文档到这里，或点击选择文件</strong>
              <span>支持 doc/docx/txt/md/html/pdf；旧版 doc 会提示转换为 docx。</span>
            </div>
          </div>
        </Dragger>
      </Card>

      <Card className="knowledge-card knowledge-card-solid" title="入库任务">
        {Object.values(jobs).length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="上传后这里会显示解析和分桶进度" />
        ) : (
          <div className="knowledge-jobs">
            {Object.values(jobs).map((job) => (
              <div className="knowledge-job" key={job.id}>
                <div className="knowledge-job-head">
                  <div>
                    <Typography.Text strong>{job.filename}</Typography.Text>
                    <Typography.Text type="secondary"> · {job.stage}</Typography.Text>
                  </div>
                  {statusTag(job.status)}
                </div>
                <Progress percent={Math.round(job.progress * 100)} status={job.status === 'failed' ? 'exception' : undefined} />
                {job.error && <Typography.Text type="danger">{job.error}</Typography.Text>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function DiscoveryColumn({
  title,
  description,
  items,
  readonly = false,
  onConfirm,
  onReject,
}: {
  title: string;
  description: string;
  items: KnowledgeDiscoveryRead[];
  readonly?: boolean;
  onConfirm: (item: KnowledgeDiscoveryRead) => Promise<void>;
  onReject: (item: KnowledgeDiscoveryRead) => Promise<void>;
}) {
  return (
    <div className="knowledge-discovery-column">
      <div className="knowledge-section-heading">
        <div>
          <strong>{title}</strong>
          <span>{description}</span>
        </div>
        <Tag>{items.length}</Tag>
      </div>
      {items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无内容" />
      ) : (
        <Space direction="vertical" size={12} className="knowledge-discovery-list">
          {items.map((item) => (
            <div className={`knowledge-discovery ${item.suggestion_type}`} key={item.id}>
              <div className="knowledge-discovery-header">
                <Space size={8} wrap>
                  <Typography.Text strong>{item.title}</Typography.Text>
                  <Tag>{typeLabel(item.suggestion_type)}</Tag>
                  {statusTag(item.status)}
                </Space>
                {!readonly && item.status === 'pending' && (
                  <Space size={8}>
                    <Button size="small" shape="circle" icon={<CheckOutlined />} onClick={() => void onConfirm(item)} />
                    <Button size="small" shape="circle" icon={<CloseOutlined />} onClick={() => void onReject(item)} />
                  </Space>
                )}
              </div>
              {item.reason && <Typography.Paragraph type="secondary">{item.reason}</Typography.Paragraph>}
              <Collapse
                ghost
                items={[
                  {
                    key: 'payload',
                    label: '查看详情',
                    children: <pre className="knowledge-json">{JSON.stringify(item.payload, null, 2)}</pre>,
                  },
                ]}
              />
            </div>
          ))}
        </Space>
      )}
    </div>
  );
}

function statusTag(status: string) {
  const map: Record<string, { color: string; label: string }> = {
    active: { color: 'green', label: '已上线' },
    published: { color: 'green', label: '已发布' },
    archived: { color: 'default', label: '已下线' },
    draft: { color: 'default', label: '草稿' },
    succeeded: { color: 'green', label: '已完成' },
    ready: { color: 'green', label: '达标' },
    confirmed: { color: 'green', label: '已确认' },
    failed: { color: 'red', label: '失败' },
    pending: { color: 'gold', label: '待处理' },
    running: { color: 'processing', label: '处理中' },
    queued: { color: 'gold', label: '排队中' },
  };
  const item = map[status] || { color: 'gold', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
}

function bucketStatusTag(bucket: KnowledgeBucketRead) {
  if (bucket.status === 'ready') return <Tag color="green">达标</Tag>;
  return <Tag color="gold">待补足</Tag>;
}

function typeLabel(type: string) {
  if (type === 'skill') return '技能';
  if (type === 'tool') return '工具';
  return '提示';
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('读取文件失败'));
    reader.onload = () => {
      const result = String(reader.result || '');
      resolve(result.includes(',') ? result.split(',').pop() || '' : result);
    };
    reader.readAsDataURL(file);
  });
}
