<?php

namespace App\Filament\Resources;

use App\Filament\Resources\OrderResource\Pages;
use App\Models\Order;
use App\Support\AdminAudit;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Support\Facades\Http;

class OrderResource extends ReadOnlyResource
{
    protected static ?string $model = Order::class;

    protected static ?string $navigationIcon = 'heroicon-o-rectangle-stack';

    protected static ?string $navigationLabel = 'Заявки';

    protected static ?string $modelLabel = 'заявка';

    protected static ?string $pluralModelLabel = 'заявки';

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('username')
                    ->disabled(),
                Forms\Components\TextInput::make('currency')
                    ->disabled(),
                Forms\Components\TextInput::make('rub_amount')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('crypto_address')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\Select::make('status')
                    ->options([
                        'pending' => 'pending',
                        'paid' => 'paid',
                        'sent' => 'sent',
                    ])
                    ->required(),
                Forms\Components\TextInput::make('paid_btc_tx')
                    ->label('TXID')
                    ->columnSpanFull(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('order_id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('order_id')
                    ->label('#')
                    ->sortable(),
                Tables\Columns\TextColumn::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('username')
                    ->searchable(),
                Tables\Columns\TextColumn::make('currency')
                    ->badge(),
                Tables\Columns\TextColumn::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('status')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'sent' => 'success',
                        'paid' => 'warning',
                        'pending' => 'gray',
                        default => 'gray',
                    })
                    ->sortable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
                Tables\Columns\TextColumn::make('paid_btc_tx')
                    ->label('TXID')
                    ->limit(16)
                    ->toggleable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->options([
                        'pending' => 'pending',
                        'paid' => 'paid',
                        'sent' => 'sent',
                    ]),
                Tables\Filters\SelectFilter::make('currency')
                    ->options([
                        'BTC' => 'BTC',
                        'LTC' => 'LTC',
                        'USDT' => 'USDT',
                    ]),
            ])
            ->actions([
                Tables\Actions\Action::make('force_payout')
                    ->label('Выплатить')
                    ->icon('heroicon-o-banknotes')
                    ->color('success')
                    ->visible(fn (Order $record): bool => $record->status === 'paid')
                    ->requiresConfirmation()
                    ->modalHeading('Принудительная выплата')
                    ->modalDescription(fn (Order $record): string => "Укажите TXID уже отправленной выплаты #{$record->order_id}.")
                    ->form([
                        Forms\Components\TextInput::make('txid')
                            ->label('TXID')
                            ->required(),
                    ])
                    ->action(function (Order $record, array $data) {
                        $record->refresh();
                        abort_unless($record->status === 'paid', 409, 'Order is no longer payable.');

                        AdminAudit::recordAction('force_payout_attempted', $record);
                        $response = Http::withHeaders([
                            'X-Internal-Secret' => config('services.internal_admin_secret'),
                        ])->post(config('services.relay_internal_url') . '/internal/admin/force_payout', [
                            'order_id' => $record->order_id,
                            'txid' => $data['txid'],
                        ]);

                        if ($response->successful()) {
                            AdminAudit::recordAction('force_payout_succeeded', $record);
                            \Filament\Notifications\Notification::make()
                                ->title('Выплата выполнена')
                                ->success()
                                ->send();
                        } else {
                            AdminAudit::recordAction('force_payout_failed', $record);
                            \Filament\Notifications\Notification::make()
                                ->title('Ошибка вызова relay')
                                ->body($response->body())
                                ->danger()
                                ->send();
                        }
                    }),
            ])
            ->bulkActions([]);
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListOrders::route('/'),
            'edit' => Pages\EditOrder::route('/{record}/edit'),
        ];
    }
}
